import json
import subprocess
import sys
from pathlib import Path

VIEWER = Path(__file__).parent.parent / "tools" / "view_transcripts.py"

ROLLOUT = {
    "id": "outer1",
    "env": {"id": "keygen"},
    "task": {"type": "KeygenTask", "data": {
        "id": "keygen-l0-0", "prompt": "write keygen.py <b>carefully</b>",
        "seed": 0, "level": 0, "reference_source": "def keygen(n): return n"}},
    "traces": [{
        "id": "inner1", "is_completed": True, "is_timeout": False,
        "stop_condition": "agent_completed", "errors": [],
        "num_total_tokens": 42,
        "rewards": {"solved": {"score": 1.0, "weight": 1.0}},
        "info": {"keygen_grading": {"scope_ok": True}},
        "timing": {"agent": {"start": 10.0, "end": 15.0}},
        "nodes": [
            {"message": {"role": "system", "content": "sys"}},
            {"message": {"role": "user", "content": "write keygen.py <b>carefully</b>"}},
            {"sampled": True, "message": {
                "role": "assistant", "reasoning_content": "hmm",
                "tool_calls": [{"id": "c1", "type": "function", "name": "bash",
                                "arguments": "{\"command\": \"ls\"}"}]}},
            {"message": {"role": "tool", "name": "bash", "content": "check\nkeygen.py"}},
        ],
        "calls": [{"node": 2, "model": "m0", "finish_reason": "tool_calls",
                   "usage": {"prompt_tokens": 10, "completion_tokens": 5},
                   "time": {"start": 11.0, "end": 12.0}}],
    }],
}


def test_view_transcripts(tmp_path):
    run = tmp_path / "keygen--m0--bash--deadbeef"
    (run / "artifacts" / "inner1" / "app" / "repo").mkdir(parents=True)
    (run / "artifacts" / "inner1" / "app" / "repo" / "keygen.py").write_text(
        "def keygen(n):\n    return SERIAL_XXXX\n")
    (run / "traces.jsonl").write_text(json.dumps(ROLLOUT) + "\n")

    out = tmp_path / "out.html"
    r = subprocess.run([sys.executable, str(VIEWER), str(tmp_path), "-o", str(out)],
                       check=False, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr

    page = out.read_text(encoding="utf-8")
    assert "keygen-l0-0" in page
    assert "solved 1.0" in page
    assert "&lt;b&gt;carefully&lt;/b&gt;" in page and "<b>carefully" not in page
    assert "check\nkeygen.py" in page  # tool output rendered
    assert "def keygen(n):" in page and "SERIAL_XXXX" in page  # artifact embedded
    assert "m0" in page and "tool_calls" in page  # call footer
