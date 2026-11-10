import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

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


DENIED_SOURCES = [
    pytest.param(
        "import os\n"
        "def f(xs):\n"
        "    os.system('true')\n"
        "    return xs[0]\n",
        id="os.system",
    ),
    pytest.param(
        "import ctypes\n"
        "def f(xs):\n"
        "    return xs[0]\n",
        id="import-ctypes",
    ),
    pytest.param(
        "import mmap\n"
        "def f(xs):\n"
        "    return xs[0]\n",
        id="import-mmap",
    ),
    pytest.param(
        "def f(xs):\n"
        "    open('/proc/self/maps').read()\n"
        "    return xs[0]\n",
        id="open-proc",
    ),
    pytest.param(
        "def g():\n"
        "    return 0\n"
        "def f(xs):\n"
        "    g.__code__ = f.__code__\n"
        "    return xs[0]\n",
        id="rewrite-__code__",
    ),
    pytest.param(
        "import os\n"
        "def f(xs):\n"
        "    os.fork()\n"
        "    return xs[0]\n",
        id="os.fork",
        marks=pytest.mark.skipif(
            not hasattr(os, "fork"), reason="os.fork is not available on Windows"
        ),
    ),
    pytest.param(
        "import os, sys\n"
        "def f(xs):\n"
        "    os.posix_spawn(sys.executable, [sys.executable, '-c', 'pass'], os.environ)\n"
        "    return xs[0]\n",
        id="os.posix_spawn",
        marks=pytest.mark.skipif(
            not hasattr(os, "posix_spawn"),
            reason="os.posix_spawn is not available on Windows",
        ),
    ),
]


@pytest.mark.parametrize("source", DENIED_SOURCES)
def test_audit_hook_denied_behaviors_fail_every_case(tmp_path, source):
    result = _run_submission(tmp_path, source)
    assert len(result["outputs"]) == 2
    assert all(output["ok"] is False for output in result["outputs"])


def test_audit_hook_control_submission_passes(tmp_path):
    result = _run_submission(tmp_path, "def f(xs):\n    return xs[0] + 1\n")
    assert all(output["ok"] is True for output in result["outputs"])


@pytest.mark.parametrize(
    ("body", "return_type", "ok"),
    [
        ("return True", "uint32", False),
        ("return 4294967296", "uint32", False),
        ("return 1.0", "uint32", False),
        ("return 42", "uint32", True),
        ("return 'serial'", "str", True),
        ("return 42", "str", False),
    ],
)
def test_runner_return_type_validation(tmp_path, body, return_type, ok):
    result = _run_submission(
        tmp_path,
        f"def f(xs):\n    {body}\n",
        return_type=return_type,
    )
    assert all(output["ok"] is ok for output in result["outputs"])
