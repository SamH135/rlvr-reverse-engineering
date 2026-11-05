import json
import os
import subprocess
import sys
from pathlib import Path

RUNNER = (
    Path(__file__).resolve().parents[1]
    / "src/rlvr_coding_env/families/common/runner.py"
)


def _run_submission(
    tmp_path: Path,
    source: str,
    *,
    case_arguments: list[list[object]] | None = None,
    function_name: str = "f",
    return_type: str = "uint32",
    arg_decode: str | None = None,
) -> dict:
    repo = tmp_path / "repo"
    grader = tmp_path / "grader"
    repo.mkdir(parents=True, exist_ok=True)
    grader.mkdir(parents=True, exist_ok=True)
    (repo / "solution.py").write_text(source, encoding="utf-8")
    cases = {
        "nonce": "test-nonce",
        "deliverable": "solution.py",
        "function_name": function_name,
        "return_type": return_type,
        "cases": case_arguments if case_arguments is not None else [[[1]], [[2]]],
    }
    if arg_decode is not None:
        cases["arg_decode"] = arg_decode
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


def test_runner_hex_decoding_and_json_return_validation(tmp_path):
    parsed = _run_submission(
        tmp_path / "parsed",
        "def parse(data):\n"
        "    return {'hex': data.hex(), 'length': len(data), "
        "'nested': [None, 7, 'ok']}\n",
        case_arguments=[["00ff"], ["6162"]],
        function_name="parse",
        return_type="json",
        arg_decode="hex",
    )
    assert parsed["outputs"] == [
        {
            "ok": True,
            "value": {"hex": "00ff", "length": 2, "nested": [None, 7, "ok"]},
        },
        {
            "ok": True,
            "value": {"hex": "6162", "length": 2, "nested": [None, 7, "ok"]},
        },
    ]

    rejected = _run_submission(
        tmp_path / "rejected",
        "def parse(data):\n    return {'invalid': True}\n",
        case_arguments=[["00"]],
        function_name="parse",
        return_type="json",
        arg_decode="hex",
    )
    assert rejected["outputs"] == [{"ok": False, "error": "TypeError"}]
