import asyncio
import importlib.util
import inspect
import types
from pathlib import Path

from hypothesis import given, settings
from hypothesis import strategies as st

from rlvr_coding_env.families.keygen.taskset import KeygenTaskset, KeygenTasksetConfig

RUNNER = (
    Path(__file__).resolve().parents[1]
    / "src/rlvr_coding_env/families/common/runner.py"
)


def _runner_module():
    spec = importlib.util.spec_from_file_location("rlvr_runner_under_test", RUNNER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


runner = _runner_module()


def _solved(grading: dict) -> float:
    task = KeygenTaskset(KeygenTasksetConfig(num_tasks=1, level=0)).load()[0]
    trace = types.SimpleNamespace(info={"keygen_grading": grading})
    value = type(task).solved(task, None, trace)
    return asyncio.run(value) if inspect.isawaitable(value) else value


GRADING = st.fixed_dictionaries(
    {
        "scope_ok": st.booleans(),
        "runner_completed": st.booleans(),
        "hidden_pass_frac": st.one_of(
            st.floats(allow_nan=False), st.integers(), st.booleans()
        ),
    }
)


@given(GRADING)
@settings(max_examples=100, deadline=None)
def test_solved_is_binary_and_one_only_when_all_conditions_hold(grading):
    reward = _solved(grading)
    assert reward in (0.0, 1.0)
    expected = bool(
        grading["scope_ok"]
        and grading["runner_completed"]
        and grading["hidden_pass_frac"] == 1.0
    )
    assert reward == float(expected)


JSON_LEAVES = st.one_of(
    st.none(),
    st.text(),
    st.integers(),
    st.booleans(),
    st.floats(allow_nan=False),
)
JSON_VALUES = st.recursive(
    JSON_LEAVES,
    lambda children: st.one_of(
        st.lists(children),
        st.dictionaries(st.text(), children),
        st.dictionaries(st.integers(), children),
    ),
    max_leaves=15,
)


def _expected_valid(value) -> bool:
    if value is None or isinstance(value, str) or type(value) is int:
        return True
    if isinstance(value, list):
        return all(_expected_valid(item) for item in value)
    if isinstance(value, dict):
        return all(
            type(key) is str and _expected_valid(item)
            for key, item in value.items()
        )
    return False


@given(JSON_VALUES)
@settings(max_examples=100, deadline=None)
def test_valid_json_value_matches_json_serializable_schema(value):
    assert runner._valid_json_value(value) is _expected_valid(value)
