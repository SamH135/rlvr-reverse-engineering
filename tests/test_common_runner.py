import json
import os
import subprocess
import sys
from pathlib import Path

RUNNER = (
    Path(__file__).resolve().parents[1]
    / "src/rlvr_coding_env/families/common/runner.py"
)


def _run_submission(tmp_path: Path, source: str) -> dict:
    repo = tmp_path / "repo"
    grader = tmp_path / "grader"
    repo.mkdir(parents=True, exist_ok=True)
    grader.mkdir(parents=True, exist_ok=True)
    (repo / "solution.py").write_text(source, encoding="utf-8")
    cases = {
        "nonce": "test-nonce",
        "deliverable": "solution.py",
        "function_name": "f",
        "return_type": "uint32",
        "cases": [[[1]], [[2]]],
    }
    cases_path = grader / "cases.json"
    result_path = grader / "result.json"
    cases_path.write_text(json.dumps(cases), encoding="utf-8")
    subprocess.run(
        [sys.executable, str(RUNNER), "--run", str(cases_path), str(result_path)],
        check=True,
        capture_output=True,
        text=True,
        env={**os.environ, "RLVR_REPO_ROOT": str(repo)},
    )
    return json.loads(result_path.read_text(encoding="utf-8"))


def test_audit_hook_rejects_subprocess_and_allows_runner_result_write(tmp_path):
    denied = _run_submission(
        tmp_path / "denied",
        "import subprocess\n"
        "def f(xs):\n"
        "    subprocess.run(['true'], check=True)\n"
        "    return xs[0]\n",
    )
    assert denied["nonce"] == "test-nonce"
    assert len(denied["outputs"]) == 2
    assert all(output["ok"] is False for output in denied["outputs"])

    gold = _run_submission(
        tmp_path / "gold",
        "def f(xs):\n    return xs[0]\n",
    )
    assert gold == {
        "nonce": "test-nonce",
        "outputs": [
            {"ok": True, "value": 1},
            {"ok": True, "value": 2},
        ],
    }
