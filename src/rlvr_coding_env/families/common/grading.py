"""Shared trusted grading for isolated function submissions."""

from __future__ import annotations

import json
from typing import Any

import verifiers.v1 as vf

GRADER_ROOT = "/grader"
RUNNER_TIMEOUT_SECONDS = 20
MAX_RESULT_BYTES = 1_000_000


async def grade_function(
    runtime: vf.Runtime, nonce: str, expected_outputs: list[dict[str, Any]]
) -> dict[str, Any]:
    scope_run = await runtime.run(
        [
            "python3",
            f"{GRADER_ROOT}/runner.py",
            "--scope",
            f"{GRADER_ROOT}/protected.json",
        ],
        {},
    )
    if scope_run.exit_code:
        raise RuntimeError("the trusted scope checker failed to run")
    try:
        scope_ok = json.loads(scope_run.stdout).get("scope_ok") is True
    except (json.JSONDecodeError, AttributeError):
        raise RuntimeError("the scope checker returned invalid output") from None

    result: dict[str, Any] = {
        "scope_ok": scope_ok,
        "hidden_pass_frac": 0.0,
        "runner_timeout": False,
        "runner_completed": False,
        "example_ok": 0.0,
    }
    if not scope_ok:
        return result
    command = (
        f"exec timeout --signal=KILL {RUNNER_TIMEOUT_SECONDS}s python3 "
        f"{GRADER_ROOT}/runner.py --run {GRADER_ROOT}/cases.json "
        f"{GRADER_ROOT}/result.json >/dev/null 2>&1"
    )
    hidden_run = await runtime.run(["sh", "-c", command], {})
    result["runner_timeout"] = hidden_run.exit_code in (124, 137)
    if result["runner_timeout"]:
        return result
    exists = await runtime.run(["test", "-f", f"{GRADER_ROOT}/result.json"], {})
    if exists.exit_code:
        return result
    size = await runtime.run(["sh", "-c", f"wc -c < {GRADER_ROOT}/result.json"], {})
    try:
        result_size = int(size.stdout.strip())
    except ValueError:
        result_size = MAX_RESULT_BYTES + 1
    if size.exit_code or result_size > MAX_RESULT_BYTES:
        return result
    raw_result = await runtime.read(
        f"{GRADER_ROOT}/result.json", max_bytes=MAX_RESULT_BYTES
    )
    try:
        payload = json.loads(raw_result)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return result
    if (
        not isinstance(payload, dict)
        or payload.get("nonce") != nonce
        or not isinstance(payload.get("outputs"), list)
        or len(payload["outputs"]) != len(expected_outputs)
        or hidden_run.exit_code != 0
    ):
        return result
    result["runner_completed"] = True
    actual_outputs = payload["outputs"]
    result["example_ok"] = float(
        json.dumps(actual_outputs[0], sort_keys=True)
        == json.dumps(expected_outputs[0], sort_keys=True)
    )
    hidden_expected = expected_outputs[1:]
    result["hidden_pass_frac"] = sum(
        json.dumps(actual, sort_keys=True) == json.dumps(expected, sort_keys=True)
        for actual, expected in zip(actual_outputs[1:], hidden_expected, strict=True)
    ) / len(hidden_expected)
    return result
