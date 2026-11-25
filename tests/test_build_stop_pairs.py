import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

import build_stop_pairs as bp
import truncate_stop as ts


def _episode(turns):
    """Nodes for (assistant_cmd, tool_output) pairs; (None, None) = plain text."""
    nodes = [
        {"message": {"role": "system", "content": "sys"}},
        {"message": {"role": "user", "content": "task"}},
    ]
    for cmd, out in turns:
        msg = {"role": "assistant", "content": ""}
        if cmd is not None:
            msg["tool_calls"] = [
                {"name": "bash", "arguments": {"command": cmd}}
            ]
        nodes.append({"message": msg})
        if out is not None:
            nodes.append({"message": {"role": "tool", "content": out}})
    return nodes


def _verify(v):
    return (f"python3 check.py n{v} S{v}", f"n{v} S{v} ACCEPTED")


def _misc(tag):
    return (f"echo {tag}", tag)


WRITE = ("cat > keygen.py <<'PY'\ndef keygen(name):\n    return 'X'\nPY", "")


def _pairs(nodes, passes, seed=7):
    turns = list(ts.iter_turns(nodes))
    return bp.pairs_for_episode(
        nodes, turns, passes, ts.verified_flags(turns), seed=seed, run="test-run"
    )


def test_verified_passing_turns_yield_pairs():
    # solves at turn 2 (k=2); verifications at 4, 6, 8 each followed by a
    # tool-calling turn -> one pair per decision point.
    nodes = _episode(
        [
            _misc("probe0"),
            _misc("probe1"),
            WRITE,
            _misc("loop3"),
            _verify(4),
            _misc("loop5"),
            _verify(6),
            _misc("loop7"),
            _verify(8),
            _misc("loop9"),
        ]
    )
    rows, info = _pairs(nodes, [False, False] + [True] * 8)
    assert info["k"] == 2 and info["decision_points"] == 3
    assert info["skipped_cap"] == 0
    assert [r["meta"]["decision_turn"] for r in rows] == [4, 6, 8]
    for row, v in zip(rows, [4, 6, 8]):
        # prefix ends exactly at v's tool outputs: no turn after v is included
        assert len(row["prompt"]) == 2 + 2 * (v + 1)
        assert row["prompt"][-1]["role"] == "tool"
        next_cmd = f"echo loop{v + 1}"
        assert next_cmd not in json.dumps(row["prompt"])
        # rejected is the single tool-call turn v+1, without its tool output
        assert len(row["rejected"]) == 1
        assert row["rejected"][0]["tool_calls"][0]["function"]["arguments"] == {
            "command": next_cmd
        }
        # chosen is one plain-text stop message
        assert row["chosen"] == [
            {"role": "assistant", "content": row["chosen"][0]["content"]}
        ]
        assert "tool_calls" not in row["chosen"][0]
        assert row["chosen"][0]["content"] in ts.STOP_WORDINGS


def test_plain_text_next_turn_yields_no_pair():
    # verified at turn 2 but turn 3 ends the episode in plain text
    nodes = _episode([WRITE, _misc("loop"), _verify(2), (None, None)])
    rows, info = _pairs(nodes, [True] * 4)
    assert rows == [] and info["drop"] == "no_decision_point"


def test_verified_turn_at_or_before_k_yields_no_pair():
    # k = 3 (final pass streak starts at 3); verifications at 1, 2, 3 all <= k
    nodes = _episode(
        [
            WRITE,
            _verify(1),
            _verify(2),
            _verify(3),
            _misc("loop4"),
            _misc("loop5"),
            _misc("loop6"),
            _misc("loop7"),
        ]
    )
    passes = [True, True, False, True, True, True, True, True]
    rows, info = _pairs(nodes, passes)
    assert info["k"] == 3
    assert rows == [] and info["drop"] == "no_decision_point"


def test_cap_spreads_points_and_counts_skips():
    # five decision points -> first plus two evenly spread; 2 skipped
    nodes = _episode(
        [WRITE, _misc("loop1")]
        + [_verify(v) for v in range(2, 7)]
        + [_misc("loop7"), _misc("loop8")]
    )
    passes = [False] + [True] * 8
    rows, info = _pairs(nodes, passes)
    assert info["k"] == 1 and info["decision_points"] == 5
    assert info["skipped_cap"] == 2
    assert [r["meta"]["decision_turn"] for r in rows] == [2, 4, 6]


def test_row_format_matches_dpo_v5_stoploop():
    nodes = _episode(
        [WRITE, _misc("loop1"), _verify(2), _misc("loop3"), _misc("loop4")]
    )
    rows, _ = _pairs(nodes, [True] * 5)
    (r,) = rows
    assert set(r) == {"prompt", "chosen", "rejected", "meta"}
    assert set(r["meta"]) == {
        "family",
        "level",
        "seed",
        "source",
        "decision_turn",
        "k",
        "rejected_from",
        "rejected_stop",
    }
    assert r["meta"]["family"] == "keygen"
    assert r["meta"]["level"] == 0
    assert r["meta"]["seed"] == 7
    assert r["meta"]["source"] == "stop_pair"
    assert r["meta"]["rejected_from"] == "test-run"
    assert r["meta"]["rejected_stop"] == "solved_then_loop"
    assert r["chosen"] != r["rejected"]
    assert [m["role"] for m in r["prompt"][:2]] == ["system", "user"]
