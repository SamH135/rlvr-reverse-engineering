"""Deterministic generation of one-bug repair tasks."""

from __future__ import annotations

import hashlib
import json
import random
from dataclasses import dataclass

from rlvr_coding_env.families.bugfix.templates import TEMPLATES, FunctionTemplate


@dataclass(frozen=True)
class BugfixInstance:
    seed: int
    template_id: str
    mutation_id: str
    target_function: str
    spec: str
    files: dict[str, str]
    protected_hashes: dict[str, str]
    reference_source: str
    hidden_inputs: list[list[object]]
    visible_cases: list[dict[str, object]]


def _render(
    source: str,
    template: FunctionTemplate,
    function_name: str,
    parameters: tuple[str, ...],
    constant_name: str,
) -> str:
    rendered = source.replace("__FUNC__", function_name)
    for index, parameter in enumerate(parameters):
        rendered = rendered.replace(f"__P{index}__", parameter)
    rendered = rendered.replace("__MISS__", constant_name)
    if template.module_constant:
        rendered = f"{constant_name} = -1\n\n{rendered}"
    return rendered


def _call(source: str, function_name: str, args: list[object]) -> object:
    namespace: dict[str, object] = {}
    exec(compile(source, "<generated-function>", "exec"), namespace)  # noqa: S102
    return namespace[function_name](*args)


def _call_result(
    source: str, function_name: str, args: list[object]
) -> dict[str, object]:
    try:
        result = _call(source, function_name, args)
        json.dumps(result, allow_nan=False)
        return {"ok": True, "value": result}
    except Exception as error:  # noqa: BLE001
        return {"ok": False, "error": type(error).__name__}


def _visible_source(function_name: str, cases: list[dict[str, object]]) -> str:
    lines = [f"from lib import {function_name}", ""]
    for case in cases:
        name = str(case["name"])
        args = case["args"]
        expected = case["expected"]
        lines.extend(
            [
                f"def {name}():",
                f"    assert {function_name}(*{args!r}) == {expected!r}",
                "",
            ]
        )
    lines.extend(
        [
            'if __name__ == "__main__":',
            f"    for _test in {[str(case['name']) for case in cases]!r}:",
            "        globals()[_test]()",
            "",
        ]
    )
    return "\n".join(lines)


def _case_pool(
    template: FunctionTemplate,
    seed: int,
    reference_source: str,
    buggy_source: str,
    function_name: str,
) -> list[list[object]]:
    for attempt in range(32):
        rng = random.Random(seed ^ 0xBB67AE85 ^ attempt)
        candidates = template.gen_inputs(rng, 100)
        if any(
            _call_result(reference_source, function_name, args)
            != _call_result(buggy_source, function_name, args)
            for args in candidates
        ):
            return candidates
    raise ValueError(
        f"mutation {template.template_id!r} produced no visible counterexample"
    )


def generate(seed: int) -> BugfixInstance:
    """Build the same task instance for every call with the same seed."""
    rng = random.Random(seed)
    template = rng.choice(TEMPLATES)
    mutation_id = rng.choice(tuple(template.mutations))
    function_name = rng.choice(template.function_names)
    parameters = tuple(rng.choice(names) for names in template.parameter_names)
    constant_name = rng.choice(("NOT_FOUND", "MISSING_INDEX", "NO_INDEX"))

    reference_source = _render(
        template.reference_source, template, function_name, parameters, constant_name
    )
    buggy_source = _render(
        template.mutations[mutation_id],
        template,
        function_name,
        parameters,
        constant_name,
    )
    candidates = _case_pool(
        template, seed, reference_source, buggy_source, function_name
    )
    counterexamples = [
        args
        for args in candidates
        if _call_result(reference_source, function_name, args)
        != _call_result(buggy_source, function_name, args)
    ]
    if not counterexamples:
        raise ValueError(
            f"mutation {template.template_id!r}/{mutation_id!r} has no counterexample"
        )

    visible_rng = random.Random(seed ^ 0x3C6EF372)
    selected = [counterexamples[0]]
    remaining = [args for args in candidates if args != selected[0]]
    selected.extend(visible_rng.sample(remaining, k=2))
    visible_cases = [
        {
            "name": f"test_visible_case_{index}",
            "args": args,
            "expected": _call(reference_source, function_name, args),
        }
        for index, args in enumerate(selected, start=1)
    ]
    visible_inputs = [case["args"] for case in visible_cases]
    hidden_inputs = []
    for attempt in range(32):
        hidden_rng = random.Random(seed ^ 0x6A09E667 ^ attempt)
        candidates = template.gen_inputs(hidden_rng, 100)
        hidden_inputs = []
        for args in candidates:
            if args not in visible_inputs and args not in hidden_inputs:
                hidden_inputs.append(args)
            if len(hidden_inputs) == 50:
                break
        if len(hidden_inputs) == 50 and any(
            _call_result(reference_source, function_name, args)
            != _call_result(buggy_source, function_name, args)
            for args in hidden_inputs
        ):
            break
    else:
        raise ValueError(
            f"mutation {template.template_id!r}/{mutation_id!r} has no hidden counterexample"
        )

    files = {
        "lib.py": buggy_source,
        "tests/test_visible.py": _visible_source(function_name, visible_cases),
    }
    protected_hashes = {
        path: hashlib.sha256(content.encode()).hexdigest()
        for path, content in files.items()
        if path != "lib.py"
    }
    return BugfixInstance(
        seed=seed,
        template_id=template.template_id,
        mutation_id=mutation_id,
        target_function=function_name,
        spec=template.spec,
        files=files,
        protected_hashes=protected_hashes,
        reference_source=reference_source,
        hidden_inputs=hidden_inputs,
        visible_cases=visible_cases,
    )
