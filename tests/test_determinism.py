import json

import pytest

from rlvr_coding_env.families.bugfix.generator import generate as bugfix_generate
from rlvr_coding_env.families.decompile.generator import (
    generate as decompile_generate,
)
from rlvr_coding_env.families.formats.generator import generate as formats_generate
from rlvr_coding_env.families.keygen.generator import generate as keygen_generate

GENERATORS = [
    pytest.param(keygen_generate, range(7), id="keygen"),
    pytest.param(decompile_generate, range(7), id="decompile"),
    pytest.param(formats_generate, range(5), id="formats"),
    pytest.param(bugfix_generate, [1, 2], id="bugfix"),
]


@pytest.mark.parametrize(
    ("generate", "levels"), GENERATORS, ids=[p.id for p in GENERATORS]
)
def test_generate_is_deterministic_and_seed_sensitive(generate, levels):
    for level in levels:
        for seed in range(3):
            assert generate(seed, level) == generate(seed, level)
        assert generate(0, level) != generate(1, level)


def test_keygen_hidden_names_exclude_example():
    for level in range(7):
        instance = keygen_generate(0, level)
        assert len(instance.hidden_names) == 50
        assert len(set(instance.hidden_names)) == 50
        assert instance.example_name not in instance.hidden_names


def test_decompile_hidden_inputs_exclude_example():
    for level in range(7):
        instance = decompile_generate(0, level)
        assert len(instance.hidden_inputs) == 50
        assert instance.example_input not in instance.hidden_inputs


def test_formats_hidden_files_exclude_samples():
    for level in range(5):
        instance = formats_generate(0, level)
        assert len(instance.hidden_files) == 50
        assert instance.valid_count == 38
        assert instance.sample_a not in instance.hidden_files


def _reference(source: str, function: str):
    namespace: dict[str, object] = {}
    exec(compile(source, "<determinism-reference>", "exec"), namespace)  # noqa: S102
    return namespace[function]


@pytest.mark.parametrize("family", ["keygen", "decompile", "formats"])
def test_hidden_outputs_are_not_constant(family):
    """Degenerate instances (constant outputs over all hidden cases) are bugs."""
    levels = range(7) if family in ("keygen", "decompile") else range(5)
    for level in levels:
        for seed in range(30):
            if family == "keygen":
                instance = keygen_generate(seed, level)
                serial = _reference(instance.reference_source, "serial")
                outputs = {serial(name) for name in instance.hidden_names}
            elif family == "decompile":
                instance = decompile_generate(seed, level)
                function = _reference(instance.reference_source, "f")
                outputs = {
                    function(xs) for xs in instance.hidden_inputs
                }
            else:
                instance = formats_generate(seed, level)
                parse = _reference(instance.reference_source, "parse")
                outputs = {
                    json.dumps(parse(data), sort_keys=True)
                    for data in instance.hidden_files[: instance.valid_count]
                }
            assert len(outputs) > 1, (
                f"{family} seed {seed} level {level}: constant hidden outputs"
            )


def test_bugfix_hidden_cases_exclude_visible_cases():
    for level in (1, 2):
        instance = bugfix_generate(0, level)
        assert len(instance.hidden_cases) == 50 * level
        visible_inputs = {
            json.dumps(case["args"]) for case in instance.visible_cases
        }
        for _function_name, args in instance.hidden_cases:
            assert json.dumps(args) not in visible_inputs
