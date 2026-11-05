import json

import pytest

from rlvr_coding_env.families.bugfix import runner
from rlvr_coding_env.families.bugfix.generator import generate


def _namespace(source: str) -> dict[str, object]:
    namespace: dict[str, object] = {}
    exec(compile(source, "<generated-function>", "exec"), namespace)  # noqa: S102
    return namespace


def _result(function, args: list[object]) -> dict[str, object]:
    try:
        value = function(*args)
        json.dumps(value, allow_nan=False)
        return {"ok": True, "value": value}
    except Exception as error:  # noqa: BLE001
        return {"ok": False, "error": type(error).__name__}


@pytest.mark.parametrize("level", [1, 2])
def test_seeded_generations_are_reproducible_and_mutation_killed(level: int):
    for seed in range(200):
        instance = generate(seed, level)
        assert instance == generate(seed, level)
        assert instance.level == level
        assert len(instance.target_functions) == level
        assert len(instance.hidden_cases) == 50 * level
        assert set(instance.protected_hashes) == {"tests/test_visible.py"}
        assert instance.files["tests/test_visible.py"].splitlines()[0] == (
            f"from lib import {', '.join(instance.target_functions)}"
        )
        assert len({case["name"] for case in instance.visible_cases}) == len(
            instance.visible_cases
        )

        reference = _namespace(instance.reference_source)
        buggy = _namespace(instance.files["lib.py"])
        for function_name in instance.target_functions:
            hidden_inputs = [
                args for name, args in instance.hidden_cases if name == function_name
            ]
            visible_cases = [
                case
                for case in instance.visible_cases
                if case["function"] == function_name
            ]
            assert len(hidden_inputs) == 50
            visible_inputs = {json.dumps(case["args"]) for case in visible_cases}
            assert all(json.dumps(args) not in visible_inputs for args in hidden_inputs)

            reference_function = reference[function_name]
            buggy_function = buggy[function_name]
            hidden_reference = [
                _result(reference_function, args) for args in hidden_inputs
            ]
            assert all(result["ok"] for result in hidden_reference)
            assert any(
                _result(reference_function, args) != _result(buggy_function, args)
                for args in hidden_inputs
            )

            visible_failed = False
            for case in visible_cases:
                expected = {"ok": True, "value": case["expected"]}
                assert _result(reference_function, case["args"]) == expected
                visible_failed |= _result(buggy_function, case["args"]) != expected

            if level == 1:
                assert visible_failed
            else:
                assert not visible_failed
                assert len(visible_cases) <= 2

        if level == 2:
            assert instance.template_ids[0] != instance.template_ids[1]
            assert instance.target_functions[0] != instance.target_functions[1]


def test_run_hidden_missing_function_is_a_case_failure(tmp_path, monkeypatch):
    lib_path = tmp_path / "lib.py"
    lib_path.write_text("def available():\n    return 1\n", encoding="utf-8")
    cases_path = tmp_path / "cases.json"
    cases_path.write_text(
        json.dumps({"nonce": "test-nonce", "cases": [["missing", []]]}),
        encoding="utf-8",
    )
    result_path = tmp_path / "result.json"
    monkeypatch.setattr(runner, "LIB_PATH", lib_path)

    runner.run_hidden(cases_path, result_path)

    assert json.loads(result_path.read_text(encoding="utf-8")) == {
        "nonce": "test-nonce",
        "outputs": [{"ok": False, "error": "AttributeError"}],
    }
