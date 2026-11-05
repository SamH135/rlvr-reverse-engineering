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
    level: int
    template_ids: list[str]
    mutation_ids: list[str]
    target_functions: list[str]
    specs: list[str]
    files: dict[str, str]
    protected_hashes: dict[str, str]
    reference_source: str
    hidden_cases: list[list[object]]
    visible_cases: list[dict[str, object]]


@dataclass(frozen=True)
class _GeneratedFunction:
    template_id: str
    mutation_id: str
    target_function: str
    spec: str
    buggy_source: str
    reference_source: str
    hidden_cases: list[list[object]]
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


def _visible_source(function_names: list[str], cases: list[dict[str, object]]) -> str:
    lines = [f"from lib import {', '.join(function_names)}", ""]
    for case in cases:
        name = str(case["name"])
        function_name = str(case["function"])
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


def _generate_function(
    seed: int,
    rng: random.Random,
    *,
    excluded_template_id: str | None,
    visible_requires_failure: bool,
    qualify_visible_names: bool,
) -> _GeneratedFunction:
    templates = (
        TEMPLATES
        if excluded_template_id is None
        else tuple(
            template
            for template in TEMPLATES
            if template.template_id != excluded_template_id
        )
    )
    template = rng.choice(templates)
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
    if visible_requires_failure:
        selected = [counterexamples[0]]
        remaining = [args for args in candidates if args != selected[0]]
        selected.extend(visible_rng.sample(remaining, k=2))
    else:
        passing = [
            args
            for args in candidates
            if _call_result(reference_source, function_name, args)
            == _call_result(buggy_source, function_name, args)
        ]
        selected = visible_rng.sample(passing, k=min(2, len(passing)))
    visible_cases = [
        {
            "name": (
                f"test_visible_case_{function_name}_{index}"
                if qualify_visible_names
                else f"test_visible_case_{index}"
            ),
            "function": function_name,
            "args": args,
            "expected": _call(reference_source, function_name, args),
        }
        for index, args in enumerate(selected, start=1)
    ]
    visible_inputs = [case["args"] for case in visible_cases]
    hidden_inputs: list[list[object]] = []
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

    return _GeneratedFunction(
        template_id=template.template_id,
        mutation_id=mutation_id,
        target_function=function_name,
        spec=template.spec,
        buggy_source=buggy_source,
        reference_source=reference_source,
        hidden_cases=[[function_name, args] for args in hidden_inputs],
        visible_cases=visible_cases,
    )


def generate(seed: int, level: int = 1) -> BugfixInstance:
    """Build the same task instance for every call with the same seed and level."""
    if level not in (1, 2):
        raise ValueError(f"unsupported bugfix level: {level}")

    first = _generate_function(
        seed,
        random.Random(seed),
        excluded_template_id=None,
        visible_requires_failure=level == 1,
        qualify_visible_names=level == 2,
    )
    functions = [first]
    if level == 2:
        second_seed = seed ^ 0x510E527F
        functions.append(
            _generate_function(
                second_seed,
                random.Random(second_seed),
                excluded_template_id=first.template_id,
                visible_requires_failure=False,
                qualify_visible_names=True,
            )
        )

    files = {
        "lib.py": "\n\n".join(function.buggy_source for function in functions),
        "tests/test_visible.py": _visible_source(
            [function.target_function for function in functions],
            [case for function in functions for case in function.visible_cases],
        ),
    }
    protected_hashes = {
        path: hashlib.sha256(content.encode()).hexdigest()
        for path, content in files.items()
        if path != "lib.py"
    }
    return BugfixInstance(
        seed=seed,
        level=level,
        template_ids=[function.template_id for function in functions],
        mutation_ids=[function.mutation_id for function in functions],
        target_functions=[function.target_function for function in functions],
        specs=[function.spec for function in functions],
        files=files,
        protected_hashes=protected_hashes,
        reference_source="\n\n".join(
            function.reference_source for function in functions
        ),
        hidden_cases=[case for function in functions for case in function.hidden_cases],
        visible_cases=[
            case for function in functions for case in function.visible_cases
        ],
    )
