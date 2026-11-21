"""Build same-seed preference pairs (DPO) from solved SFT rows + failed rollouts.

Usage: py -m uv run python tools/build_dpo.py [sft/train_v2_c.jsonl] [-o sft/dpo_v1.jsonl]
Pair per (family, level, train seed): chosen = the solved episode's turns; rejected = a failed
attempt's turns on the SAME task. The shared prompt comes from the solved row. A failed run
pairs only if its task prompt equals the solved row's user message, or differs solely in the
grading sentence (0.3.4 wording / none vs 0.3.5) — the rewrite_sft_prompts rule.
Rejected candidates: real attempts only (provider/harness/sandbox errors excluded); up to 2
per key, student models first; tails truncated at --rej-chars so long loops still fit.
Output rows: {"prompt": [sys, user], "chosen": [...], "rejected": [...], "meta": {...}}.
meta.prompt_diff records "same" | "grading-sentence"; review each pair before training.
"""

import argparse
import collections
import glob
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from build_sft import convert

EVAL_SEED_BASE = 1_000_000
INFRA = {"provider_error", "harness_error", "sandbox_error"}
STUDENT = ("re-v3c", "re-tmp", "re-sft", "qwen3-4b-inst-base", "qwen3-1p7b")
NOUN = {"decompile": "program", "formats": "reader", "keygen": "checker"}
OLD_SENT = (
    "Grading runs in a fresh sandbox where the provided {n} is not present and "
    "starting subprocesses is blocked, so the solution must be self-contained "
    "Python."
)
NEW_SENT = (
    "Grading happens later, in a fresh sandbox where the provided {n} is not "
    "present and starting subprocesses is blocked, so your final solution must "
    "be self-contained Python. While you work, you may run the provided {n} "
    "and any tools freely."
)


def _ungrade(text: str, noun: str) -> str:
    return text.replace(" " + OLD_SENT.format(n=noun), "").replace(" " + NEW_SENT.format(n=noun), "")


def failed_runs():
    for p in sorted(glob.glob("outputs/*/traces.jsonl")):
        run = Path(p).parent.name
        for line in Path(p).read_text(encoding="utf8").splitlines():
            try:
                e = json.loads(line)
                t = e["traces"][0]
            except (ValueError, KeyError, IndexError):
                continue
            d = t["task"]["data"]
            if d.get("access", "default") != "default" or (d.get("seed") or EVAL_SEED_BASE) >= EVAL_SEED_BASE:
                continue
            if t["rewards"].get("solved", {}).get("score") == 1.0 or t.get("stop_condition") in INFRA or t.get("errors"):
                continue
            yield e["env"]["id"], d.get("level"), d.get("seed"), run, d.get("prompt"), convert(t["nodes"]), t.get("stop_condition")


def truncate(msgs, cap):
    """Keep the first 2 turns plus as many trailing turns as fit: the failure's ending matters most."""
    if sum(len(json.dumps(m)) for m in msgs) <= cap:
        return msgs, False
    head, tail, total = msgs[:2], [], sum(len(json.dumps(m)) for m in msgs[:2])
    for m in reversed(msgs[2:]):
        c = len(json.dumps(m))
        if total + c > cap:
            break
        total += c
        tail.append(m)
    return head + tail[::-1], True


def build(src, max_chars, rej_chars, per_key=2):
    solved = {}
    for line in Path(src).read_text(encoding="utf8").splitlines():
        row = json.loads(line)
        m = row["meta"]
        solved[(m["family"], m["level"], m["seed"])] = row

    picks = collections.defaultdict(list)
    for fam, lvl, seed, run, prompt, msgs, stop in failed_runs():
        row = solved.get((fam, lvl, seed))
        if row is None:
            continue
        if prompt == row["messages"][1]["content"]:
            diff = "same"
        elif _ungrade(prompt or "", NOUN[fam]) == _ungrade(row["messages"][1]["content"], NOUN[fam]):
            diff = "grading-sentence"
        else:
            continue
        picks[(fam, lvl, seed)].append((0 if any(s in run for s in STUDENT) else 1, run, msgs, diff, stop))

    out, stats = [], collections.Counter()
    for (fam, lvl, seed), cands in picks.items():
        row = solved[(fam, lvl, seed)]
        seen_model, used = set(), []
        for c in sorted(cands, key=lambda x: x[0]):
            model = c[1].split("--")[1]
            if model not in seen_model:
                seen_model.add(model)
                used.append(c)
        for _, run, rej, diff, stop in used[:per_key]:
            rej, trunc = truncate(rej, rej_chars)
            if sum(len(json.dumps(m)) for m in row["messages"] + rej) > max_chars:
                stats["too_long"] += 1
                continue
            out.append(
                {
                    "prompt": row["messages"][:2],
                    "chosen": row["messages"][2:],
                    "rejected": rej,
                    "meta": {
                        "family": fam,
                        "level": lvl,
                        "seed": seed,
                        "rejected_from": run,
                        "rejected_stop": stop,
                        "rejected_truncated": trunc,
                        "prompt_diff": diff,
                    },
                }
            )
            stats[(fam, lvl)] += 1
    return out, stats


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("src", nargs="?", default="sft/train_v2_c.jsonl")
    ap.add_argument("-o", default="sft/dpo_v1.jsonl")
    ap.add_argument("--max-chars", type=int, default=16000)
    ap.add_argument("--rej-chars", type=int, default=8000)
    ap.add_argument("--per-key", type=int, default=2)
    ap.add_argument("--dry", action="store_true", help="print candidate pairs, write nothing")
    a = ap.parse_args()
    out, stats = build(a.src, a.max_chars, a.rej_chars, a.per_key)
    if a.dry:
        for i, r in enumerate(out):
            m = r["meta"]
            print(
                f"{i:3d} {m['family']}-L{m['level']} s{m['seed']} rej={m['rejected_from'].split('--')[1]} "
                f"stop={m['rejected_stop']} diff={m['prompt_diff']} trunc={m['rejected_truncated']} "
                f"nturns={len(r['rejected'])}"
            )
    else:
        Path(a.o).write_text("".join(json.dumps(r) + "\n" for r in out), encoding="utf8")
        print(f"{len(out)} pairs -> {a.o}")
    for k, v in sorted(stats.items(), key=str):
        print(k, v)


if __name__ == "__main__":
    main()
