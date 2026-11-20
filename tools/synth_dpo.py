"""Synthetic DPO rejections: the student's most common failure is quitting before verification.

Usage: py -m uv run python tools/synth_dpo.py [sft/train_v2_c.jsonl] [-o sft/dpo_synth.jsonl]
For each solved row: keep every turn up to the first real verification command (a bash call that
imports/runs solution.py, or the last tool exchange if none), then replace the rest with a
plain-text "done" reply — a coherent early-quit trajectory. One pair per row.
meta.synthetic=True; keep this a bounded share of any DPO mix.
"""

import argparse
import json
import random
import re
from pathlib import Path

VERIFY = re.compile(r"python3?|solution\.py|check|test")
WRITE = re.compile(r"cat\s*>|str_replace|old_str|write_text|open\(")
DONE = [
    "Done. I implemented the solution in {t}.",
    "Done — the deliverable is written and should be correct.",
    "The solution is implemented; I'm confident it matches the required behavior.",
    "Finished. {t} now reproduces the expected output.",
]


DELIVERABLE = re.compile(r"(?:stub|deliverable)[^./]*?/app/repo/(\w+\.py)", re.IGNORECASE)


def synth_reject(row, rng):
    m = DELIVERABLE.search(row["messages"][1]["content"])
    target = m.group(1) if m else "solution.py"
    msgs = row["messages"][2:]
    w = next(
        (
            i
            for i, msg in enumerate(msgs)
            if msg["role"] == "assistant"
            and target in json.dumps(msg.get("tool_calls", ""))
            and WRITE.search(json.dumps(msg.get("tool_calls", "")))
        ),
        None,
    )
    if w is None:
        return None
    v = next(
        (
            i
            for i in range(w + 1, len(msgs))
            if msgs[i]["role"] == "assistant"
            and any(VERIFY.search(str(tc.get("function", {}).get("arguments", ""))) for tc in msgs[i].get("tool_calls", []))
        ),
        None,
    )
    # verified trace: cut just before the check. unverified trace: cut right after the write.
    rej = msgs[:v] if v is not None else msgs[: w + 2]
    if rej[-1]["role"] == "assistant" and rej[-1].get("tool_calls"):
        rej = rej[:-1]  # don't leave a dangling call
    if len(rej) < 2 or len(rej) >= len(msgs) - 1:
        return None  # rejected must drop real content, not mirror chosen
    return rej + [{"role": "assistant", "content": rng.choice(DONE).format(t=target)}]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("src", nargs="?", default="sft/train_v2_c.jsonl")
    ap.add_argument("-o", default="sft/dpo_synth.jsonl")
    ap.add_argument("--seed", type=int, default=0)
    a = ap.parse_args()
    rng = random.Random(a.seed)
    out = []
    for line in Path(a.src).read_text(encoding="utf8").splitlines():
        row = json.loads(line)
        rej = synth_reject(row, rng)
        if rej:
            out.append(
                {
                    "prompt": row["messages"][:2],
                    "chosen": row["messages"][2:],
                    "rejected": rej,
                    "meta": {**row["meta"], "synthetic": True, "rejected_from": "synth_earlyquit"},
                }
            )
    Path(a.o).write_text("".join(json.dumps(r) + "\n" for r in out), encoding="utf8")
    print(f"{len(out)} synthetic pairs -> {a.o}")


if __name__ == "__main__":
    main()
