import pytest

from rlvr_coding_env.families.bugfix.taskset import (
    BugfixTaskset,
    BugfixTasksetConfig,
)
from rlvr_coding_env.families.common import EVAL_SEED_BASE
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
    (BugfixTaskset, BugfixTasksetConfig, 1, "bugfix"),
    (KeygenTaskset, KeygenTasksetConfig, 0, "keygen-l0"),
    (DecompileTaskset, DecompileTasksetConfig, 0, "decompile-l0"),
    (FormatsTaskset, FormatsTasksetConfig, 0, "formats-l0"),
]


@pytest.mark.parametrize(
    ("taskset_type", "config_type", "level", "id_prefix"),
    TASKSETS,
)
def test_seed_splits_preserve_train_ids_and_start_eval_at_base(
    taskset_type, config_type, level, id_prefix
):
    train = taskset_type(config_type(num_tasks=2, level=level)).load()
    assert [task.data.seed for task in train] == [0, 1]
    assert [task.data.id for task in train] == [f"{id_prefix}-0", f"{id_prefix}-1"]

    evaluation = taskset_type(
        config_type(num_tasks=2, level=level, split="eval")
    ).load()
    assert [task.data.seed for task in evaluation] == [
        EVAL_SEED_BASE,
        EVAL_SEED_BASE + 1,
    ]
    assert [task.data.id for task in evaluation] == [
        f"{id_prefix}-{EVAL_SEED_BASE}",
        f"{id_prefix}-{EVAL_SEED_BASE + 1}",
    ]

    with pytest.raises(ValueError, match="train split seed range"):
        taskset_type(
            config_type(
                num_tasks=2,
                seed_offset=EVAL_SEED_BASE - 1,
                split="train",
                level=level,
            )
        ).load()
