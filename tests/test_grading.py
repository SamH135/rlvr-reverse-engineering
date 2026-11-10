import asyncio
import json

import pytest

from rlvr_coding_env.families.common.grading import (
    MAX_RESULT_BYTES,
    grade_function,
)

NONCE = "test-nonce"


def _expected(values: list[object]) -> list[dict[str, object]]:
    return [{"ok": True, "value": value} for value in values]


def _result_bytes(nonce: str, outputs: list[dict[str, object]]) -> bytes:
    return json.dumps({"nonce": nonce, "outputs": outputs}).encode()


def _grade(runtime, expected, **kwargs):
    return asyncio.run(grade_function(runtime, NONCE, expected, **kwargs))


def test_scope_not_ok_returns_early_and_never_invokes_runner(fake_runtime):
    runtime = fake_runtime(scope_stdout='{"scope_ok": false}')
    result = _grade(runtime, _expected([1, 2]))
    assert result["scope_ok"] is False
    assert result["hidden_pass_frac"] == 0.0
    assert result["runner_completed"] is False
    assert runtime.runner_invoked is False


def test_scope_exit_nonzero_raises(fake_runtime):
    runtime = fake_runtime(scope_exit=1)
    with pytest.raises(RuntimeError, match="scope checker failed"):
        _grade(runtime, _expected([1, 2]))


def test_scope_stdout_garbage_raises(fake_runtime):
    runtime = fake_runtime(scope_stdout="not json")
    with pytest.raises(RuntimeError, match="invalid output"):
        _grade(runtime, _expected([1, 2]))


@pytest.mark.parametrize("exit_code", [124, 137])
def test_runner_timeout_exit_codes(exit_code, fake_runtime):
    runtime = fake_runtime(run_exit=exit_code)
    result = _grade(runtime, _expected([1, 2]))
    assert result["runner_timeout"] is True
    assert result["runner_completed"] is False


def test_missing_result_file_returns_early(fake_runtime):
    runtime = fake_runtime(result_exists=False)
    result = _grade(runtime, _expected([1, 2]))
    assert result["runner_completed"] is False
    assert result["hidden_pass_frac"] == 0.0


def test_result_over_max_bytes_returns_early(fake_runtime):
    runtime = fake_runtime(result_size=MAX_RESULT_BYTES + 1)
    result = _grade(runtime, _expected([1, 2]))
    assert result["runner_completed"] is False


def test_invalid_result_json_returns_early(fake_runtime):
    runtime = fake_runtime(result=b"this is not json")
    result = _grade(runtime, _expected([1, 2]))
    assert result["runner_completed"] is False


def test_nonce_mismatch_returns_early(fake_runtime):
    runtime = fake_runtime(result=_result_bytes("other-nonce", _expected([1, 2])))
    result = _grade(runtime, _expected([1, 2]))
    assert result["runner_completed"] is False


def test_wrong_output_count_returns_early(fake_runtime):
    runtime = fake_runtime(result=_result_bytes(NONCE, _expected([1])))
    result = _grade(runtime, _expected([1, 2]))
    assert result["runner_completed"] is False


def test_runner_nonzero_exit_returns_early(fake_runtime):
    runtime = fake_runtime(run_exit=1, result=_result_bytes(NONCE, _expected([1, 2])))
    result = _grade(runtime, _expected([1, 2]))
    assert result["runner_completed"] is False
    assert result["runner_timeout"] is False


def test_all_outputs_match_scores_perfect(fake_runtime):
    values = [10, 20, 30]
    runtime = fake_runtime(result=_result_bytes(NONCE, _expected(values)))
    result = _grade(runtime, _expected(values))
    assert result["scope_ok"] is True
    assert result["runner_completed"] is True
    assert result["example_ok"] == 1.0
    assert result["hidden_pass_frac"] == 1.0


def test_one_hidden_mismatch_scores_fraction(fake_runtime):
    expected = _expected([1, 2, 3, 4])
    actual = _expected([1, 2, 3, 99])
    runtime = fake_runtime(result=_result_bytes(NONCE, actual))
    result = _grade(runtime, expected)
    assert result["runner_completed"] is True
    assert result["example_ok"] == 1.0
    assert result["hidden_pass_frac"] == pytest.approx(2 / 3)


@pytest.mark.parametrize(("actual", "expected"), [(True, 1), (1.0, 1)])
def test_canonical_comparison_rejects_type_substitutes(
    actual, expected, fake_runtime
):
    runtime = fake_runtime(
        result=_result_bytes(NONCE, _expected([actual, 7]))
    )
    result = _grade(runtime, _expected([expected, 7]))
    assert result["example_ok"] == 0.0
    assert result["hidden_pass_frac"] == 1.0


def test_include_case_passes_returns_per_case_list(fake_runtime):
    expected = _expected([1, 2, 3])
    actual = _expected([1, 2, 99])
    runtime = fake_runtime(result=_result_bytes(NONCE, actual))
    result = _grade(runtime, expected, include_case_passes=True)
    assert result["case_passes"] == [True, True, False]
