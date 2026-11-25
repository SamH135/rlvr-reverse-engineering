"""Build prefix-shared "stop vs continue" DPO pairs from keygen L0 traces.

Usage: py -m uv run python tools/build_stop_pairs.py [-o sft/dpo_v6_stop.jsonl]

Same candidate pool and replay+grading as truncate_stop.py (which see): each
solve-then-loop episode's bash calls are replayed in rlvr-keygen:0.2 and every
post-turn snapshot is graded with the real runner.py. At every assistant turn
v AFTER the last stable pass where the snapshot still passes AND the recorded
tool output verified the solution AND the next assistant turn keeps calling
tools, emit one pair:

  prompt   = history through turn v's tool outputs (ends on a tool message)
  chosen   = an honest stop message (STOP_WORDINGS, seeded per (seed, v))
  rejected = the actual next assistant turn v+1 (tool calls, no tool output)

Cap per episode: the first decision point plus up to 2 more, evenly spread.
Rows are {"prompt", "chosen", "rejected", "meta"} like sft/dpo_v5_stoploop.jsonl.
"""

import argparse
import collections
import glob
import json
import os
import random
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import truncate_stop as ts
from build_sft import convert

from rlvr_coding_env.families.keygen.generator import generate

MAX_PAIRS = 3


def decision_points(turns, passes, verified):
    """(k, [v...]): verified still-passing turns v > k whose next turn calls a
    tool. k is None when the replay never reached a stable pass."""
    k = ts.last_stable_pass(passes)
    if k is None:
        return None, []
    pts = [
        v
        for v in range(k + 1, len(turns) - 1)
        if passes[v] and verified[v] and turns[v + 1][2].get("tool_calls")
    ]
    return k, pts


def spread(points, cap=MAX_PAIRS):
    """First point plus up to `cap - 1` more, evenly spread through the last."""
    if len(points) <= cap:
        return list(points)
    idx = {int(j * (len(points) - 1) / (cap - 1) + 0.5) for j in range(cap)}
    return [points[i] for i in sorted(idx)]


def make_row(nodes, turns, v, *, seed, k, run, max_chars):
    """One pair for decision point v, or (None, drop_reason)."""
    prompt = convert(nodes[: turns[v][1] + 1])
    if len(json.dumps(prompt)) > max_chars:
        return None, "too_long"
    stop = random.Random(f"{seed}:{v}").choice(ts.STOP_WORDINGS)
    chosen = [{"role": "assistant", "content": stop}]
    rejected = convert([nodes[turns[v + 1][0]]])
    if chosen == rejected:
        return None, "chosen_eq_rejected"
    if not ts.bash_commands(turns[v + 1][2]):
        return None, "rejected_not_bash"
    return {
        "prompt": prompt,
        "chosen": chosen,
        "rejected": rejected,
        "meta": {
            "family": "keygen",
            "level": 0,
            "seed": seed,
            "source": "stop_pair",
            "decision_turn": v,
            "k": k,
            "rejected_from": run,
            "rejected_stop": "solved_then_loop",
        },
    }, None


def pairs_for_episode(
    nodes, turns, passes, verified, *, seed, run, cap=MAX_PAIRS, max_chars=16000
):
    """(rows, info): pairs at the kept decision points, or ([], {"drop": ...})."""
    k, pts = decision_points(turns, passes, verified)
    if k is None:
        return [], {"drop": "replay_did_not_reproduce_solve"}
    if not pts:
        return [], {"drop": "no_decision_point", "k": k}
    keep = spread(pts, cap)
    rows, pair_drops = [], collections.Counter()
    for v in keep:
        row, reason = make_row(
            nodes, turns, v, seed=seed, k=k, run=run, max_chars=max_chars
        )
        if row is None:
            pair_drops[f"pair_drop:{reason}"] += 1
        else:
            rows.append(row)
    info = {
        "k": k,
        "decision_points": len(pts),
        "skipped_cap": len(pts) - len(keep),
        "turns": len(turns),
        **pair_drops,
    }
    return rows, info


def process_episode(t, work_root, run, *, image=ts.IMAGE, max_chars=16000, cap=MAX_PAIRS):
    """Replay + grade one candidate trace, then build its pairs."""
    d = t["task"]["data"]
    seed = d["seed"]
    inst = generate(seed, 0)
    work = work_root / f"seed{seed}"
    ts._write_grading_files(inst, work)
    expected = ts._expected_outputs(inst)
    turns = list(ts.iter_turns(t["nodes"]))
    cmds = [ts.bash_commands(m) for _, _, m, _ in turns]
    if any(c is None for c in cmds):
        return [], {"drop": "non_bash_tool_call"}
    snaps, err = ts.replay(cmds, inst, image)
    if err:
        return [], {"drop": err}
    verified = ts.verified_flags(turns)
    passes = []
    for i, s in enumerate(snaps):
        if i and s is not None and s == snaps[i - 1]:
            passes.append(passes[-1])
        else:
            passes.append(ts.grade_snapshot(s, work / f"turn{i:03d}", work, expected))
    return pairs_for_episode(
        t["nodes"],
        turns,
        passes,
        verified,
        seed=seed,
        run=run,
        cap=cap,
        max_chars=max_chars,
    )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-o", default="sft/dpo_v6_stop.jsonl")
    ap.add_argument("--glob", action="append")
    ap.add_argument("--max-chars", type=int, default=16000)
    ap.add_argument("--cap", type=int, default=MAX_PAIRS)
    ap.add_argument("--image", default=ts.IMAGE)
    a = ap.parse_args()
    kept, stats, per_seed = [], collections.Counter(), collections.Counter()
    seen = set()
    paths = sorted(p for g in (a.glob or ts.DEFAULT_GLOBS) for p in glob.glob(g))
    with tempfile.TemporaryDirectory(prefix="stop-pairs-") as tmp:
        work_root = Path(tmp)
        for p in paths:
            run = Path(p).parent.name
            for line in Path(p).read_text(encoding="utf8").splitlines():
                try:
                    e = json.loads(line)
                    t = e["traces"][0]
                except (ValueError, KeyError, IndexError):
                    continue
                if not ts.is_candidate(e, t):
                    continue
                seed = t["task"]["data"]["seed"]
                stats["candidates"] += 1
                if seed in seen:
                    stats["dup_seed"] += 1
                    continue
                seen.add(seed)
                rows, info = process_episode(
                    t, work_root, run, image=a.image, max_chars=a.max_chars, cap=a.cap
                )
                if info.get("drop"):
                    stats[f"drop:{info['drop']}"] += 1
                    print(run, "seed", seed, "DROP", info, flush=True)
                    continue
                stats["episodes_with_k"] += 1
                stats["decision_points"] += info["decision_points"]
                stats["skipped_cap"] += info["skipped_cap"]
                for key in info:
                    if key.startswith("pair_drop:"):
                        stats[key] += info[key]
                kept.extend(rows)
                per_seed[seed] += len(rows)
                print(run, "seed", seed, "PAIRS", len(rows), info, flush=True)
    os.makedirs(os.path.dirname(a.o) or ".", exist_ok=True)
    with open(a.o, "w", encoding="utf8") as f:
        f.writelines(json.dumps(r) + "\n" for r in kept)
    print(len(kept), "pairs ->", a.o)
    for k, v in sorted(stats.items(), key=str):
        print(k, v)
    print("pairs per seed:", dict(sorted(per_seed.items())))


if __name__ == "__main__":
    main()
