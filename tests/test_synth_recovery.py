import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from synth_recovery import inject


def _call(cmd):
    return {"role": "assistant", "content": "", "tool_calls": [{"type": "function", "function": {"name": "bash", "arguments": {"command": cmd}}}]}


def _row(verify):
    return {"messages": [{"role": "system", "content": "s"}, {"role": "user", "content": "u"},
                         _call("cat > solution.py <<'EOF'\ndef f(x):\n    return x\nEOF"), {"role": "tool", "content": ""},
                         _call(verify), {"role": "tool", "content": "ok\n"}], "meta": {"family": "keygen"}}


def test_injects_nameerror_before_real_check():
    v = 'cd /app/repo && python3 -c "\nfrom solution import f\nprint(f(1))\n"'
    out = inject(_row(v))
    m = out["messages"]
    assert len(m) == 8 and m[6] == _call(v) and m[7]["content"] == "ok\n"
    bad = m[4]["tool_calls"][0]["function"]["arguments"]["command"]
    assert "import" not in bad and "print(f(1))" in bad
    assert m[5]["content"].endswith("NameError: name 'f' is not defined\n") and "line 2" in m[5]["content"]
    assert out["meta"]["synthetic"] is True


def test_skips_multiline_writes_and_no_import():
    assert inject(_row("python3 -c \"print(1)\"")) is None
    assert inject(_row('python3 -c "from solution import f\nprint(1)\nprint(f(1))"')) is None
    assert inject(_row("cd /app/repo && ./prog 1 2")) is None
