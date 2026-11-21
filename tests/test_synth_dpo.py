import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from synth_dpo import synth_reject


def _call(cmd):
    return {"role": "assistant", "content": "", "tool_calls": [{"type": "function", "function": {"name": "bash", "arguments": {"command": cmd}}}]}


def _row():
    return {"messages": [{"role": "system", "content": "s"}, {"role": "user", "content": "u"},
                         _call("ls"), {"role": "tool", "content": "files"},
                         _call("cat > solution.py <<'EOF'\ndef f(x):\n    return x\nEOF"), {"role": "tool", "content": ""},
                         _call('python3 -c "from solution import f; print(f(1))"'), {"role": "tool", "content": "1"},
                         {"role": "assistant", "content": "Done."}],
            "meta": {}}


def test_cuts_before_verification_and_ends_with_done():
    rej = synth_reject(_row(), random.Random(0))
    assert rej is not None and rej[-1]["role"] == "assistant" and rej[-1]["content"].startswith(("Done", "The", "Finished"))
    assert len(rej) == 5  # explore + write + its reply + done text
    assert all("import" not in str(m.get("tool_calls", "")) for m in rej)
