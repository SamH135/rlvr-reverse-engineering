import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

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


LOOP = ("cat keygen.py", "def keygen(name: str) -> str:\n    return '0000-0000'\n")
WRITE = ("cat > keygen.py <<'PY'\ndef keygen(name):\n    return 'X'\nPY", "")
ACCEPT = ("python3 check.py abc XXXX-XXXX", "abc XXXX-XXXX ACCEPTED")
REJECT = ("python3 check.py abc XXXX-XXXX", "abc XXXX-XXXX REJECTED")


def test_solve_verify_loop_cuts_after_verification():
    # solves at turn 3, verifies at turn 4, loops until turn 10 -> cut at 4
    nodes = _episode(
        [
            ("ls -la /app/repo", "check.py keygen.py"),
            ("python3 -c \"print('probe')\"", "probe"),
            WRITE,
            ("python3 -c \"print('thinking')\"", "thinking"),
            ACCEPT,
            LOOP,
            LOOP,
            LOOP,
            LOOP,
            LOOP,
        ]
    )
    turns = list(ts.iter_turns(nodes))
    assert len(turns) == 10
    passes = [False] * 3 + [True] * 7
    v, reason = ts.choose_cut(passes, ts.verified_flags(turns))
    assert reason is None and v == 4
    msgs = ts.truncate_messages(nodes, turns[v][1], "Done.")
    assert msgs[-1] == {"role": "assistant", "content": "Done."}
    assert "tool_calls" not in msgs[-1]
    assert not any("tool_calls" in m for m in msgs[-1:])
    assert len(msgs) == 2 + 5 * 2 + 1  # head + turns 0-4 (msg+tool) + stop turn
    assert msgs[-2]["role"] == "tool"  # cut after the verification turn


def test_no_verification_after_solve_is_dropped():
    nodes = _episode([WRITE, REJECT, LOOP, LOOP, LOOP])
    passes = [True] * 5
    v, reason = ts.choose_cut(passes, ts.verified_flags(list(ts.iter_turns(nodes))))
    assert v is None and reason == "no_verification_after_solve"


def test_break_after_first_pass_uses_last_stable_pass():
    # first pass at 2, broken at 4, stable again from 5 -> k = 5
    nodes = _episode(
        [WRITE, ("true", ""), ("true", ""), ACCEPT, LOOP, ("true", ""), ("true", ""), ACCEPT, LOOP, LOOP]
    )
    turns = list(ts.iter_turns(nodes))
    passes = [False, False, True, True, False, True, True, True, True, True]
    verified = ts.verified_flags(turns)
    assert verified[3] and verified[7]
    assert ts.last_stable_pass(passes) == 5
    v, reason = ts.choose_cut(passes, verified)
    assert reason is None and v == 7  # not turn 3: it precedes the last stable pass


def test_verification_heuristic():
    # a checker ACCEPTED line counts even mid-line (`name serial ACCEPTED`)
    assert ts.turn_is_verification(["python3 check.py a b"], ["a b ACCEPTED"])
    # a clean test exercising keygen counts
    assert ts.turn_is_verification(
        ["python3 - <<'PY'\nfrom keygen import keygen\nprint(keygen('a'))\nPY"],
        ["a 13A2-E66A"],
    )
    # cat-ing the checker source is not verification (REJECTED in the source)
    assert not ts.turn_is_verification(
        ["cat check.py"], ["print('ACCEPTED' if accepted else 'REJECTED')"]
    )
    # visible failure markers are not success
    assert not ts.turn_is_verification(
        ["python3 - <<'PY'\nfrom keygen import keygen\nPY"], ["x 1 False"]
    )
    # inspecting the deliverable is not a test on it
    assert not ts.turn_is_verification(["cat keygen.py"], ["def keygen(name):"])
