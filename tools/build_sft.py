"""Build an SFT jsonl from solved default-access teacher traces.

Usage: uv run python tools/build_sft.py [-o sft/train.jsonl] [--max-level 4] [--per-task 1]
Each line: {"messages": [...], "tools": [...], "meta": {...}} (Qwen/Hermes tool-call shape).
Held out by design: levels > --max-level (generalization eval) and seeds >= EVAL_SEED_BASE.
"""
import argparse
import collections
import glob
import json
import os
from pathlib import Path

EVAL_SEED_BASE = 1_000_000
CAP = 2000


def clip(s):
    return s if len(s) <= CAP else s[: CAP * 2 // 3] + "\n...[truncated]...\n" + s[-CAP // 3 :]


def _is_json(s):
    try:
        json.loads(s)
        return True
    except (ValueError, TypeError):
        return False


def convert(nodes):
    msgs = []
    for n in nodes:
        m = n["message"]
        r = m["role"]
        if r == "assistant":
            out = {"role": "assistant", "content": m.get("content") or ""}
            if m.get("tool_calls"):
                out["tool_calls"] = [
                    {"type": "function", "function": {"name": c["name"], "arguments": c["arguments"] if isinstance(c["arguments"], dict) else (json.loads(c["arguments"]) if _is_json(c["arguments"]) else {"_raw": c["arguments"]})}}
                    for c in m["tool_calls"]
                ]
            msgs.append(out)
        elif r == "tool":
            msgs.append({"role": "tool", "content": clip(str(m["content"]))})
        elif r in ("user", "system"):
            msgs.append({"role": r, "content": m["content"]})
    return msgs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-o", default="sft/train.jsonl")
    ap.add_argument("--max-level", type=int, default=4)
    ap.add_argument("--per-task", type=int, default=1)
    ap.add_argument("--max-chars", type=int, default=16000)
    ap.add_argument("--glob", default="outputs/*--deepseek-flash--*/traces.jsonl")
    ap.add_argument("--clean-stop", action="store_true", help="keep only solves that ended agent_completed (drops solve-then-loop)")
    a = ap.parse_args()
    seen, kept, stats = collections.Counter(), [], collections.Counter()
    for p in sorted(glob.glob(a.glob)):
        for line in Path(p).read_text(encoding="utf8").splitlines():
            try:
                e = json.loads(line)
                t = e["traces"][0]
            except (ValueError, KeyError, IndexError):  # truncated/partial trace line
                continue
            d = t["task"]["data"]
            fam, lvl, seed, acc = e["env"]["id"], d.get("level"), d.get("seed"), d.get("access", "default")
            if acc != "default" or lvl is None or lvl > a.max_level or seed is None or seed >= EVAL_SEED_BASE:
                continue
            if t["rewards"].get("solved", {}).get("score") != 1.0 or t.get("errors"):
                continue
            if a.clean_stop and t.get("stop_condition") != "agent_completed":
                stats["not_clean_stop"] += 1
                continue
            key = (fam, lvl, seed)
            if seen[key] >= a.per_task:
                continue
            msgs = convert(t["nodes"])
            if sum(len(json.dumps(m)) for m in msgs) > a.max_chars:
                stats["too_long"] += 1
                continue
            seen[key] += 1
            stats[(fam, lvl)] += 1
            kept.append({"messages": msgs, "tools": [{"type": "function", "function": {k: v for k, v in x.items() if k != "type"}} for x in t["tools"]], "meta": {"family": fam, "level": lvl, "seed": seed}})
    os.makedirs(os.path.dirname(a.o) or ".", exist_ok=True)
    with open(a.o, "w", encoding="utf8") as f:
        f.writelines(json.dumps(r) + "\n" for r in kept)
    print(len(kept), "episodes ->", a.o)
    for k, v in sorted(stats.items(), key=str):
        print(k, v)


if __name__ == "__main__":
    main()
