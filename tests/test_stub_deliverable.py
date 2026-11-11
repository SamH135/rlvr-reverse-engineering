"""Deliverable stubs are pre-created by setup() and stay agent-editable."""

import ast
import json
from types import SimpleNamespace

import pytest

from rlvr_coding_env.families.decompile.taskset import (
    DecompileTaskset,
    DecompileTasksetConfig,
)
from rlvr_coding_env.families.formats.taskset import (
    FormatsTaskset,
    FormatsTasksetConfig,
)
from rlvr_coding_env.families.keygen.taskset import KeygenTaskset, KeygenTasksetConfig

TASKSETS = {
    "keygen": (KeygenTaskset, KeygenTasksetConfig, "keygen.py", "keygen"),
    "decompile": (DecompileTaskset, DecompileTasksetConfig, "solution.py", "f"),
    "formats": (FormatsTaskset, FormatsTasksetConfig, "parser.py", "parse"),
}


class RecordingRuntime:
    def __init__(self):
        self.writes: list[tuple[str, bytes]] = []

    async def run(self, argv, env):
        return SimpleNamespace(exit_code=0, stdout="", stderr="")

    async def write(self, path, content):
        self.writes.append((path, bytes(content)))

    async def read(self, path, max_bytes=1_000_000):
        raise FileNotFoundError(path)


def _task(family: str):
    taskset_cls, config_cls, _, _ = TASKSETS[family]
    taskset = taskset_cls(config=config_cls(level=0, num_tasks=1))
    return taskset.load()[0]


@pytest.mark.parametrize("family", sorted(TASKSETS))
def test_setup_writes_stub_deliverable_last(family):
    _, _, deliverable, function_name = TASKSETS[family]
    task = _task(family)
    runtime = RecordingRuntime()
    import asyncio

    asyncio.run(task.setup(None, runtime))
    stub_path = f"/app/repo/{deliverable}"
    stub_writes = [w for w in runtime.writes if w[0] == stub_path]
    assert stub_writes, f"no stub written to {stub_path}"
    assert runtime.writes[-1][0] == stub_path, "stub must be the last write in setup()"
    source = stub_writes[-1][1].decode()
    tree = ast.parse(source)  # compiles
    names = {n.name for n in tree.body if isinstance(n, ast.FunctionDef)}
    assert function_name in names
    namespace: dict = {}
    exec(compile(tree, "<stub>", "exec"), namespace)  # noqa: S102
    with pytest.raises(NotImplementedError):
        namespace[function_name](b"")


@pytest.mark.parametrize("family", sorted(TASKSETS))
def test_stub_matches_verifier_deliverable_and_is_unprotected(family):
    _, _, deliverable, function_name = TASKSETS[family]
    task = _task(family)
    runtime = RecordingRuntime()
    import asyncio

    asyncio.run(task.stage_verifier(None, runtime))
    cases_write = next(w for w in runtime.writes if w[0].endswith("cases.json"))
    cases = json.loads(cases_write[1])
    assert cases["deliverable"] == deliverable
    assert cases["function_name"] == function_name
    assert deliverable not in (task.data.protected_hashes or {})
    assert deliverable not in (task.data.files or {})
