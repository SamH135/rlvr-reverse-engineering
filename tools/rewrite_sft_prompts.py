"""Rewrite stored SFT prompts to the current taskset's grading-sentence wording.

Usage: uv run python tools/rewrite_sft_prompts.py [raw=sft/train_raw.jsonl out=sft/train_v2.jsonl]

For each episode, the first user message must equal the prompt the CURRENT
taskset generates for (family, level, seed) except possibly the grading
sentence: the old wording ("Grading runs in a fresh sandbox ...") or none at
all. Episodes whose stored prompt differs in any other way are dropped. A B
variant (system message suffixed with baselines/prompt_c.txt) is written too;
episodes whose B messages exceed the build_sft length cap are dropped from
both outputs.
"""
import json
import shutil
import sys
from pathlib import Path

from rlvr_coding_env.families.decompile.taskset import (
    DecompileTaskset,
    DecompileTasksetConfig,
)
from rlvr_coding_env.families.formats.taskset import (
    FormatsTaskset,
    FormatsTasksetConfig,
)
from rlvr_coding_env.families.keygen.taskset import (
    KeygenTaskset,
    KeygenTasksetConfig,
)

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "sft" / "train_raw.jsonl"
OUT = ROOT / "sft" / "train_v2.jsonl"
OUT_C = ROOT / "sft" / "train_v2_c.jsonl"
PROMPT_C = ROOT / "baselines" / "prompt_c.txt"
MAX_CHARS = 16000  # same measure as tools/build_sft.py --max-chars

TASKSETS = {
    "keygen": (KeygenTaskset, KeygenTasksetConfig),
    "decompile": (DecompileTaskset, DecompileTasksetConfig),
    "formats": (FormatsTaskset, FormatsTasksetConfig),
}
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


def _prompt(family: str, level: int, seed: int) -> str:
    cls, cfg = TASKSETS[family]
    task = cls(config=cfg(num_tasks=1, seed_offset=seed, level=level)).load()[0]
    assert task.data.seed == seed
    return task.data.prompt


def _ungrade(text: str, noun: str) -> str:
    """Remove the grading sentence (either wording, or absent) plus its space."""
    return text.replace(" " + OLD_SENT.format(n=noun), "").replace(
        " " + NEW_SENT.format(n=noun), ""
    )


def _first_diff(a: str, b: str) -> str:
    i = next((k for k, (x, y) in enumerate(zip(a, b)) if x != y), min(len(a), len(b)))
    return f"pos {i}: stored=...{a[max(0, i - 40):i + 40]!r} regen=...{b[max(0, i - 40):i + 40]!r}"


def main() -> int:
    suffix = PROMPT_C.read_text(encoding="utf-8").rstrip("\n")
    shutil.copy(ROOT / "sft" / "train.jsonl", ROOT / "sft" / "train.jsonl.bak")

    kept, stats, diff_examples = [], {}, {}
    for line in RAW.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        rec = json.loads(line)
        meta = rec["meta"]
        fam, lvl, seed = meta["family"], meta["level"], meta["seed"]
        stats.setdefault((fam, lvl), {"raw": 0, "kept": 0, "other": 0, "long": 0})
        stats[(fam, lvl)]["raw"] += 1
        regen = _prompt(fam, lvl, seed)
        msgs = rec["messages"]
        i = next(k for k, m in enumerate(msgs) if m["role"] == "user")
        if _ungrade(msgs[i]["content"], NOUN[fam]) != _ungrade(regen, NOUN[fam]):
            stats[(fam, lvl)]["other"] += 1
            diff_examples.setdefault(fam, _first_diff(msgs[i]["content"], regen))
            continue
        msgs[i]["content"] = regen
        b_msgs = [dict(m) for m in msgs]
        assert b_msgs[0]["role"] == "system"
        b_msgs[0]["content"] = b_msgs[0]["content"] + "\n\n" + suffix
        if sum(len(json.dumps(m)) for m in b_msgs) > MAX_CHARS:
            stats[(fam, lvl)]["long"] += 1
            continue
        stats[(fam, lvl)]["kept"] += 1
        kept.append((rec, b_msgs))

    with OUT.open("w", encoding="utf-8") as f:
        for rec, _ in kept:
            f.write(json.dumps(rec) + "\n")
    with OUT_C.open("w", encoding="utf-8") as f:
        for rec, b_msgs in kept:
            f.write(json.dumps({**rec, "messages": b_msgs}) + "\n")

    # Second pass: re-verify written file against fresh regeneration and raw.
    raw_by_key = {}
    for line in RAW.read_text(encoding="utf-8").splitlines():
        if line.strip():
            r = json.loads(line)
            raw_by_key[(r["meta"]["family"], r["meta"]["level"], r["meta"]["seed"])] = r
    verified = mismatch = 0
    for line in OUT.read_text(encoding="utf-8").splitlines():
        rec = json.loads(line)
        m = rec["meta"]
        key = (m["family"], m["level"], m["seed"])
        i = next(k for k, x in enumerate(rec["messages"]) if x["role"] == "user")
        ok = rec["messages"][i]["content"] == _prompt(*key)
        rest_a = [x for j, x in enumerate(rec["messages"]) if j != i]
        rest_b = [x for j, x in enumerate(raw_by_key[key]["messages"]) if j != i]
        ok = ok and json.dumps(rest_a) == json.dumps(rest_b)
        ok = ok and rec["tools"] == raw_by_key[key]["tools"]
        verified, mismatch = verified + ok, mismatch + (not ok)

    for k in sorted(stats):
        print(k, stats[k])
    print("kept", len(kept), "verified", verified, "mismatch", mismatch)
    for fam, d in diff_examples.items():
        print("other-diff example", fam, ":", d)
    return 0


if __name__ == "__main__":
    sys.exit(main())
