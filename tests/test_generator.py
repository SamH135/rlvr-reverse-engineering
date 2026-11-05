import json

from rlvr_coding_env.families.bugfix.generator import generate


def _load(source: str, function_name: str):
    namespace: dict[str, object] = {}
    exec(compile(source, "<generated-function>", "exec"), namespace)  # noqa: S102
    return namespace[function_name]


def _result(function, args: list[object]) -> dict[str, object]:
    try:
        value = function(*args)
        json.dumps(value, allow_nan=False)
        return {"ok": True, "value": value}
    except Exception as error:  # noqa: BLE001
        return {"ok": False, "error": type(error).__name__}


def test_seeded_generations_are_reproducible_and_mutation_killed():
    for seed in range(200):
        instance = generate(seed)
        assert instance == generate(seed)
        assert len(instance.hidden_inputs) == 50
        visible_inputs = {json.dumps(case["args"]) for case in instance.visible_cases}
        assert all(
            json.dumps(args) not in visible_inputs for args in instance.hidden_inputs
        )
        assert set(instance.protected_hashes) == {"tests/test_visible.py"}

        reference = _load(instance.reference_source, instance.target_function)
        buggy = _load(instance.files["lib.py"], instance.target_function)

        hidden_reference = [_result(reference, args) for args in instance.hidden_inputs]
        hidden_buggy = [_result(buggy, args) for args in instance.hidden_inputs]
        assert all(result["ok"] for result in hidden_reference)
        assert hidden_buggy != hidden_reference

        visible_failed = False
        for case in instance.visible_cases:
            expected = {"ok": True, "value": case["expected"]}
            assert _result(reference, case["args"]) == expected
            visible_failed |= _result(buggy, case["args"]) != expected
        assert visible_failed
