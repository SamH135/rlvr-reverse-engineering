import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import build_dpo


def _solved_row(tmp_path, seed):
    row = {"messages": [{"role": "system", "content": "s"}, {"role": "user", "content": "TASK"},
                        {"role": "assistant", "content": "", "tool_calls": []}],
           "meta": {"family": "keygen", "level": 0, "seed": seed}}
    f = tmp_path / "sft.jsonl"
    f.write_text(json.dumps(row) + "\n")
    return f


def _ep(seed, prompt, solved, stop="agent_completed"):
    tr = {"task": {"data": {"seed": seed, "level": 0, "access": "default", "prompt": prompt}},
          "rewards": {"solved": {"score": 1.0 if solved else 0.0}},
          "stop_condition": stop, "errors": [],
          "nodes": [{"message": {"role": "assistant", "content": "x", "tool_calls": []}}],
          "tools": []}
    return {"env": {"id": "keygen"}, "traces": [tr]}


def test_failed_runs_filters(tmp_path, monkeypatch):
    eps = [_ep(1, "TASK", False), _ep(2, "TASK", False, "provider_error"),
           _ep(1, "DIFFERENT", False), _ep(3_000_000, "TASK", False), _ep(1, "TASK", True)]
    d = tmp_path / "outputs" / "keygen--m--bash--x"
    d.mkdir(parents=True)
    (d / "traces.jsonl").write_text("".join(json.dumps(e) + "\n" for e in eps))
    monkeypatch.chdir(tmp_path)
    got = [(f, l, s, p) for f, l, s, _run, p, _msgs, _stop in build_dpo.failed_runs()]
    assert got == [("keygen", 0, 1, "TASK"), ("keygen", 0, 1, "DIFFERENT")]
