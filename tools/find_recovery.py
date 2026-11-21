"""Select solved episodes that show real recovery: a failed check after the deliverable was written, then a fix.

Usage: py tools/find_recovery.py "outputs/*--google--*/traces.jsonl" ... [-o sft/recovery.jsonl] [--max-chars 16000]
Keeps an episode only if ALL hold:
  solved, default access, train seed (< EVAL_SEED_BASE), no recorded errors, fits --max-chars,
  a tool output matching ERR appears after the first deliverable write,
  the deliverable is written again after that failing output (the fix),
  no tool call is repeated 3+ times in a row (rejects the identical-failing-command loop).
Output rows match tools/build_sft.py plus meta.source (the run dir).
"""

import argparse
import glob
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from build_sft import convert

EVAL_SEED_BASE = 1_000_000
ERR = re.compile(r"Traceback|\w+Error\b|mismatch|FAIL|Assertion|differs|!= ", re.IGNORECASE)
WRITE = re.compile(r"cat\s*>|str_replace|old_str|write_text|open\(")


def _writes(m):
    s = json.dumps(m.get("tool_calls", ""))
    return m["role"] == "assistant" and "solution.py" in s and bool(WRITE.search(s))


def recovery_ok(msgs):
    w = [i for i, m in enumerate(msgs) if _writes(m)]
    if len(w) < 2:
        return False
    bad = [i for i, m in enumerate(msgs) if m["role"] == "tool" and i > w[0] and ERR.search(m["content"])]
    if not bad or w[-1] < bad[0]:
        return False
    calls = [json.dumps(m.get("tool_calls", "")) for m in msgs if m["role"] == "assistant" and m.get("tool_calls")]
    return not any(calls[i] == calls[i + 1] == calls[i + 2] for i in range(len(calls) - 2))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("globs", nargs="+")
    ap.add_argument("-o", default="sft/recovery.jsonl")
    ap.add_argument("--max-chars", type=int, default=16000)
    a = ap.parse_args()
    kept, seen, solved = [], set(), 0
    for g in a.globs:
        for p in sorted(glob.glob(g)):
            for line in Path(p).read_text(encoding="utf8").splitlines():
                try:
                    e = json.loads(line)
                    t = e["traces"][0]
                except (ValueError, KeyError, IndexError):
                    continue
                d = t["task"]["data"]
                if d.get("access", "default") != "default" or (d.get("seed") or EVAL_SEED_BASE) >= EVAL_SEED_BASE:
                    continue
                if t["rewards"].get("solved", {}).get("score") != 1.0 or t.get("errors"):
                    continue
                solved += 1
                msgs = convert(t["nodes"])
                key = (p, d["id"])
                if key in seen or sum(len(json.dumps(m)) for m in msgs) > a.max_chars or not recovery_ok(msgs):
                    continue
                seen.add(key)
                tools = [{"type": "function", "function": {k: v for k, v in x.items() if k != "type"}} for x in t["tools"]]
                kept.append({"messages": msgs, "tools": tools, "meta": {"family": e["env"]["id"], "level": d.get("level"), "seed": d.get("seed"), "source": Path(p).parent.name, "recovery": True}})
    Path(a.o).parent.mkdir(parents=True, exist_ok=True)
    Path(a.o).write_text("".join(json.dumps(r) + "\n" for r in kept), encoding="utf8")
    print(f"{len(kept)} recovery episodes of {solved} solved -> {a.o}")


if __name__ == "__main__":
    main()
