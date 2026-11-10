import asyncio
import inspect
import types

import pytest

from rlvr_coding_env.families.bugfix.taskset import (
    BugfixTaskset,
    BugfixTasksetConfig,
)
from rlvr_coding_env.families.decompile.taskset import (
    DecompileTaskset,
    DecompileTasksetConfig,
)
from rlvr_coding_env.families.formats.taskset import (
    FormatsTaskset,
    FormatsTasksetConfig,
)
from rlvr_coding_env.families.keygen.taskset import KeygenTaskset, KeygenTasksetConfig

TASKSETS = [
    pytest.param(
        BugfixTaskset,
        BugfixTasksetConfig,
        1,
        "bugfix_grading",
        {"hidden_pass_frac": 1.0},
        id="bugfix",
    ),
    pytest.param(
        KeygenTaskset,
        KeygenTasksetConfig,
        0,
        "keygen_grading",
        {"hidden_pass_frac": 1.0},
        id="keygen",
    ),
    pytest.param(
        DecompileTaskset,
        DecompileTasksetConfig,
        0,
        "decompile_grading",
        {"hidden_pass_frac": 1.0},
        id="decompile",
    ),
    pytest.param(
        FormatsTaskset,
        FormatsTasksetConfig,
        0,
        "formats_grading",
        {"valid_pass_frac": 1.0, "invalid_pass_frac": 1.0},
        id="formats",
    ),
]


@pytest.mark.parametrize(
    ("taskset_type", "config_type", "level", "cache_key", "pass_keys"), TASKSETS
)
def test_solved_rewards(taskset_type, config_type, level, cache_key, pass_keys):
    task = taskset_type(config_type(num_tasks=1, level=level)).load()[0]

    def solved(overrides):
        grading = {
            "scope_ok": True,
            "runner_completed": True,
            **pass_keys,
        }
        grading.update(overrides)
        trace = types.SimpleNamespace(info={cache_key: grading})
        value = type(task).solved(task, None, trace)
        return asyncio.run(value) if inspect.isawaitable(value) else value

    assert solved({}) == 1.0
    assert solved({"scope_ok": False}) == 0.0
    assert solved({"runner_completed": False}) == 0.0
    for key in pass_keys:
        assert solved({key: 0.99}) == 0.0
