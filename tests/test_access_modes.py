"""Opt-in `access` modes: validation and blackbox setup behavior."""

import asyncio
import shutil
from pathlib import Path
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
    "keygen": (KeygenTaskset, KeygenTasksetConfig),
    "decompile": (DecompileTaskset, DecompileTasksetConfig),
    "formats": (FormatsTaskset, FormatsTasksetConfig),
}
BLACKBOX_FAMILIES = ("decompile", "formats")


class RecordingRuntime:
    def __init__(self):
        self.calls: list[list[str]] = []
        self.writes: list[tuple[str, bytes]] = []
        self.events: list[tuple[str, object]] = []

    async def run(self, argv, env):
        self.calls.append([str(a) for a in argv])
        self.events.append(("run", list(argv)))
        return SimpleNamespace(exit_code=0, stdout="", stderr="")

    async def write(self, path, content):
        self.writes.append((path, bytes(content)))
        self.events.append(("write", path))

    async def read(self, path, max_bytes=1_000_000):
        raise FileNotFoundError(path)


def _taskset(family: str, **config):
    cls, cfg = TASKSETS[family]
    return cls(config=cfg(num_tasks=1, **config))


@pytest.mark.parametrize("family", sorted(TASKSETS))
def test_static_access_rejected(family):
    with pytest.raises(ValueError, match="infeasible"):
        _taskset(family, level=4, access="static").load()


@pytest.mark.parametrize("family", BLACKBOX_FAMILIES)
def test_blackbox_requires_binary_level(family):
    with pytest.raises(ValueError, match="level >= 2"):
        _taskset(family, level=1, access="blackbox").load()


def test_blackbox_rejected_for_keygen():
    with pytest.raises(ValueError, match="meaningless"):
        _taskset("keygen", level=4, access="blackbox").load()


@pytest.mark.parametrize("family", BLACKBOX_FAMILIES)
def test_blackbox_setup_and_task_data(family):
    task = _taskset(family, level=2, access="blackbox").load()[0]
    assert task.data.access == "blackbox"
    assert task.data.agent_user == "agent"
    assert "execute-only" in task.data.prompt
    runtime = RecordingRuntime()
    asyncio.run(task.setup(None, runtime))
    gcc = next(c for c in runtime.calls if c[0] == "gcc")
    assert "-static" in gcc, gcc
    harden = runtime.calls[-1]
    assert harden[:2] == ["sh", "-c"], harden
    assert "useradd" in harden[2] and "chmod 0111" in harden[2]
    assert "chown root:root" in harden[2]
    assert "chown -R agent:agent" in harden[2]
    # the stub must be written BEFORE the recursive chown so it ends agent-owned
    stub_write = next(
        i for i, e in enumerate(runtime.events) if e[0] == "write" and "solution.py" in str(e[1]) or e[0] == "write" and "parser.py" in str(e[1])
    )
    harden_run = max(i for i, e in enumerate(runtime.events) if e[0] == "run")
    assert stub_write < harden_run


def test_default_setup_leaves_stub_root_owned_and_unchowned():
    task = _taskset("decompile", level=2).load()[0]
    runtime = RecordingRuntime()
    asyncio.run(task.setup(None, runtime))
    assert not any("chown" in " ".join(c) for c in runtime.calls)


def test_default_setup_unchanged():
    task = _taskset("keygen", level=3).load()[0]
    assert task.data.agent_user is None
    runtime = RecordingRuntime()
    asyncio.run(task.setup(None, runtime))
    commands = [" ".join(c) for c in runtime.calls]
    assert commands == [
        "rm -rf /tmp/keygen-build",
        "mkdir -p /tmp/keygen-build",
        "gcc -O2 /tmp/keygen-build/check.c -o /tmp/keygen-build/check",
        "strip /tmp/keygen-build/check",
        "cp /tmp/keygen-build/check /app/repo/check",
        "rm -rf /tmp/keygen-build",
    ]
    assert "execute-only" not in task.data.prompt
    assert "objdump" in task.data.prompt


@pytest.mark.parametrize(
    "family,noun",
    [("decompile", "program"), ("formats", "reader"), ("keygen", "checker")],
)
def test_prompt_states_fresh_sandbox_without_provided_binary(family, noun):
    task = _taskset(family, level=2).load()[0]
    assert (
        f"Grading runs in a fresh sandbox where the provided {noun} is not "
        "present and starting subprocesses is blocked" in task.data.prompt
    )


@pytest.mark.docker
@pytest.mark.skipif(shutil.which("docker") is None, reason="docker unavailable")
@pytest.mark.parametrize("family", BLACKBOX_FAMILIES)
def test_blackbox_binary_is_execute_only_in_container(family):
    """As uid 1000: reading the hardened binary fails, executing it works."""
    import subprocess

    repo = Path(__file__).resolve().parents[1]
    inner = (
        f"from rlvr_coding_env.families.{family}.generator import generate;"
        "open('/tmp/b.c','w').write(generate(0,4).c_source)"
    )
    runner = (
        f"PYTHONPATH=/w/src python3 -c \"{inner}\" && "
        "gcc -static -O2 /tmp/b.c -o /app/repo/b && strip /app/repo/b && "
        "useradd -m agent && chown root:root /app/repo/b && chmod 0111 /app/repo/b && "
        "su agent -c 'cat /app/repo/b' ; echo CAT_RC=$?; "
        "su agent -c '/app/repo/b' ; echo EXEC_RC=$?"
    )
    result = subprocess.run(
        ["docker", "run", "--rm", "-v", f"{repo}:/w", "rlvr-keygen:0.2",
         "sh", "-c", runner],
        capture_output=True, text=True, timeout=300, check=False)
    assert "CAT_RC=1" in result.stdout, result.stdout + result.stderr
    assert "EXEC_RC=" in result.stdout and "EXEC_RC=126" not in result.stdout.replace(
        "EXEC_RC=127", ""), result.stdout + result.stderr
