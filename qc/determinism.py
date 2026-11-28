"""Regrade the gold attacker and require an identical result (grader determinism)."""

from __future__ import annotations

IGNORE = ("attacker", "pass", "expected")


async def gold_repeats(rows, attacks, run_case, config, levels=(0, 3)):
    gold = next(a for a in attacks if a["name"] == "gold")
    repeats = []
    for level in levels:
        for seed in gold["seeds"]:
            first = next(
                r
                for r in rows
                if r["attacker"] == "gold" and r["level"] == level and r["seed"] == seed
            )
            again = await run_case({**gold, "name": "gold_repeat"}, seed, level, config)
            same = all(again[k] == v for k, v in first.items() if k not in IGNORE)
            again["pass"] = again["pass"] and same
            repeats.append(again)
    return repeats
