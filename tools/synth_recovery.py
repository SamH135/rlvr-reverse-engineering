"""Inject one realistic failed check (forgotten import -> NameError) before a real passing verification step.

Usage: py tools/synth_recovery.py [sft/train_v2_c.jsonl] [-o sft/recovery_synth.jsonl] [--max 36]
For each solved episode, find the first bash call V that is `[cd ... &&] python3 -c "<script>"` (script imports the
solution, V does not itself write it, nothing prints before the first use). Insert, right before V, a copy V'
with the import removed plus the exact NameError traceback python would print, then keep V and its real reply.
Caveat: SFT also trains on the injected failing assistant turn, so keep this a small, flagged share of the data.
"""

import argparse
import json
import random
import re
from pathlib import Path

CALL = re.compile(r'^(?:cd [^\n&;]+ && )?python3? -c "(?P<s>.*)"\s*$', re.DOTALL)
IMP = re.compile(r"^[ \t]*from solution import (?P<n>\w+)[^\n]*\n", re.MULTILINE)
WRITE = re.compile(r"cat\s*>|str_replace|old_str|write_text|open\(")


def _cmd(m):
    tc = (m.get("tool_calls") or [{}])[0].get("function", {})
    a = tc.get("arguments")
    return a.get("command") if tc.get("name") == "bash" and isinstance(a, dict) else None


def _variant(cmd):
    """Return (V', traceback) or None if V is not eligible."""
    c = CALL.match(cmd)
    if not c or "cat >" in cmd or cmd.count("python") != 1:
        return None
    s, imp = c["s"], IMP.search(c["s"])
    if not imp:
        return None
    name, s2 = imp["n"], s[: imp.start()] + s[imp.end():]
    lines = s2.split("\n")
    use = next((i for i, ln in enumerate(lines) if re.search(rf"\b{name}\(", ln)), None)
    if use is None or any("print(" in ln for ln in lines[:use]):
        return None
    tb = f'Traceback (most recent call last):\n  File "<string>", line {use + 1}, in <module>\nNameError: name \'{name}\' is not defined\n'
    return cmd[: c.start("s")] + s2 + cmd[c.end("s"):], tb


def inject(row):
    msgs = row["messages"]
    w = next((i for i, m in enumerate(msgs) if m["role"] == "assistant" and "solution.py" in json.dumps(m.get("tool_calls", "")) and WRITE.search(json.dumps(m.get("tool_calls", "")))), None)
    if w is None:
        return None
    for j in range(w + 1, len(msgs) - 1):
        cmd = _cmd(msgs[j]) if msgs[j]["role"] == "assistant" else None
        v = _variant(cmd) if cmd else None
        if v:
            bad = json.loads(json.dumps(msgs[j]))
            bad["content"] = ""
            bad["tool_calls"][0]["function"]["arguments"]["command"] = v[0]
            return {**row, "messages": msgs[:j] + [bad, {"role": "tool", "content": v[1]}] + msgs[j:], "meta": {**row["meta"], "synthetic": True, "synth_kind": "noimport_nameerror"}}
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("src", nargs="?", default="sft/train_v2_c.jsonl")
    ap.add_argument("-o", default="sft/recovery_synth.jsonl")
    ap.add_argument("--max", type=int, default=36)
    a = ap.parse_args()
    out = [r for r in map(inject, map(json.loads, Path(a.src).read_text(encoding="utf8").splitlines())) if r and len(json.dumps(r["messages"])) <= 16000]
    sel = random.Random(0).sample(out, min(a.max, len(out)))
    Path(a.o).write_text("".join(json.dumps(r) + "\n" for r in sel), encoding="utf8")
    print(f"eligible {len(out)}, selected {len(sel)} -> {a.o}")


if __name__ == "__main__":
    main()
