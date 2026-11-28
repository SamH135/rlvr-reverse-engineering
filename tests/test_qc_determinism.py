import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "qc"))
from determinism import gold_repeats

ATTACKS = [{"name": "gold", "seeds": [0, 1], "expected_reward": 1.0}]


def _row(level, seed, reward=1.0, frac=1.0):
    return {
        "attacker": "gold", "level": level, "seed": seed, "reward": reward,
        "scope_ok": True, "hidden_pass_frac": frac, "pass": reward == 1.0,
    }


def _run(rows, regrade):
    async def run_case(attack, seed, level, config):
        assert attack["name"] == "gold_repeat"
        return regrade(level, seed)

    return asyncio.run(gold_repeats(rows, ATTACKS, run_case, None))


def test_identical_regrade_passes():
    rows = [_row(lv, s) for lv in (0, 3) for s in (0, 1)]
    out = _run(rows, _row)
    assert len(out) == 4 and all(r["pass"] for r in out)


def test_drifting_regrade_fails():
    rows = [_row(lv, s) for lv in (0, 3) for s in (0, 1)]
    out = _run(rows, lambda lv, s: _row(lv, s, frac=0.9 if s else 1.0))
    assert [r["pass"] for r in out] == [True, False, True, False]
