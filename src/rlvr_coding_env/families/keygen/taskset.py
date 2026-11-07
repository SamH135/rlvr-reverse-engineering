"""Verifiers taskset for isolated keygen reverse-engineering tasks."""

from __future__ import annotations

import asyncio
import json
import secrets
from importlib.resources import files
from typing import Any, Literal

import verifiers.v1 as vf
from pydantic import Field
from verifiers.v1.utils.artifacts import collect

from rlvr_coding_env.families.common import EVAL_SEED_BASE
from rlvr_coding_env.families.common.grading import grade_function
from rlvr_coding_env.families.keygen.generator import generate

REPO_ROOT = "/app/repo"
GRADER_ROOT = "/grader"


class KeygenData(vf.TaskData):
    seed: int
    level: int
    files: dict[str, str]
    expected_files: list[str]
    protected_hashes: dict[str, str]
    check_c_source: str
    reference_source: str
    example_name: str
    example_serial: str
    hidden_names: list[str]


class KeygenTask(vf.Task[KeygenData]):
    NEEDS_CONTAINER = True

    async def setup(self, trace: vf.Trace, runtime: vf.Runtime) -> None:
        for path, content in self.data.files.items():
            await runtime.write(f"{REPO_ROOT}/{path}", content.encode("utf-8"))
        if self.data.level == 0:
            return

        await runtime.run(["rm", "-rf", "/tmp/keygen-build"], {})
        await runtime.run(["mkdir", "-p", "/tmp/keygen-build"], {})
        await runtime.write(
            "/tmp/keygen-build/check.c", self.data.check_c_source.encode("utf-8")
        )
        if self.data.level == 1:
            await runtime.write(
                f"{REPO_ROOT}/check.c", self.data.check_c_source.encode("utf-8")
            )
        optimization = "-O0" if self.data.level <= 2 else "-O2"
        compiled = await runtime.run(
            [
                "gcc",
                optimization,
                "/tmp/keygen-build/check.c",
                "-o",
                "/tmp/keygen-build/check",
            ],
            {},
        )
        if compiled.exit_code:
            raise RuntimeError("could not compile the keygen checker")
        if self.data.level >= 3:
            stripped = await runtime.run(["strip", "/tmp/keygen-build/check"], {})
            if stripped.exit_code:
                raise RuntimeError("could not strip the keygen checker")
        copied = await runtime.run(
            ["cp", "/tmp/keygen-build/check", f"{REPO_ROOT}/check"], {}
        )
        if copied.exit_code:
            raise RuntimeError("could not install the keygen checker")
        removed = await runtime.run(["rm", "-rf", "/tmp/keygen-build"], {})
        if removed.exit_code:
            raise RuntimeError("could not remove temporary keygen source")

    async def stage_verifier(self, trace: vf.Trace, runtime: vf.Runtime) -> None:
        runner = (
            files("rlvr_coding_env.families.common").joinpath("runner.py").read_bytes()
        )
        nonce = secrets.token_urlsafe(32)
        cases = {
            "nonce": nonce,
            "deliverable": "keygen.py",
            "function_name": "keygen",
            "return_type": "str",
            "cases": [
                [name] for name in [self.data.example_name, *self.data.hidden_names]
            ],
        }
        protected = {
            "deliverable": "keygen.py",
            "expected_files": self.data.expected_files,
            "hashes": self.data.protected_hashes,
        }
        self._grading_nonce = nonce
        await runtime.write(f"{GRADER_ROOT}/runner.py", runner)
        await runtime.write(
            f"{GRADER_ROOT}/cases.json",
            json.dumps(cases, allow_nan=False).encode("utf-8"),
        )
        await runtime.write(
            f"{GRADER_ROOT}/protected.json",
            json.dumps(protected, sort_keys=True).encode("utf-8"),
        )
        result = await runtime.run(["rm", "-f", f"{GRADER_ROOT}/result.json"], {})
        if result.exit_code:
            raise RuntimeError("could not clear the grader result file")

    async def _grading(self, runtime: vf.Runtime, trace: vf.Trace) -> dict[str, Any]:
        cached = trace.info.get("keygen_grading")
        if cached is not None:
            return cached
        lock = getattr(self, "_grading_lock", None)
        if lock is None:
            lock = asyncio.Lock()
            self._grading_lock = lock
        async with lock:
            cached = trace.info.get("keygen_grading")
            if cached is not None:
                return cached
            result = await self._compute_grading(runtime)
            trace.info["keygen_grading"] = result
            return result

    async def _compute_grading(self, runtime: vf.Runtime) -> dict[str, Any]:
        namespace: dict[str, object] = {}
        exec(  # noqa: S102
            compile(
                self.data.reference_source,
                "<trusted-keygen-reference>",
                "exec",
            ),
            namespace,
        )
        reference = namespace["serial"]
        expected = [{"ok": True, "value": self.data.example_serial}] + [
            {"ok": True, "value": reference(name)} for name in self.data.hidden_names
        ]
        return await grade_function(runtime, self._grading_nonce, expected)

    @vf.metric
    async def scope_ok(self, runtime: vf.Runtime, trace: vf.Trace) -> float:
        return float((await self._grading(runtime, trace))["scope_ok"])

    @vf.metric
    async def hidden_pass_frac(self, runtime: vf.Runtime, trace: vf.Trace) -> float:
        return float((await self._grading(runtime, trace))["hidden_pass_frac"])

    @vf.metric
    async def runner_timeout(self, runtime: vf.Runtime, trace: vf.Trace) -> float:
        return float((await self._grading(runtime, trace))["runner_timeout"])

    @vf.metric
    async def example_ok(self, runtime: vf.Runtime, trace: vf.Trace) -> float:
        return float((await self._grading(runtime, trace))["example_ok"])

    @vf.reward(weight=1.0)
    async def solved(self, runtime: vf.Runtime, trace: vf.Trace) -> float:
        grade = await self._grading(runtime, trace)
        return float(
            grade["scope_ok"]
            and grade["runner_completed"]
            and grade["hidden_pass_frac"] == 1.0
        )

    async def validate(self, runtime: vf.Runtime, trace: vf.Trace) -> bool:
        keygen_source = (
            f"{self.data.reference_source}\n"
            "def keygen(name: str) -> str:\n"
            "    return serial(name)\n"
        )
        await runtime.write(f"{REPO_ROOT}/keygen.py", keygen_source.encode("utf-8"))
        await self.finalize(trace, runtime)
        trace.state.artifacts = await collect(
            runtime,
            self.data.artifacts,
            max_bytes=self.data.artifact_max_bytes,
        )
        await vf.grade_submission(self, trace, runtime)
        return trace.reward == 1.0


class KeygenTasksetConfig(vf.TasksetConfig):
    num_tasks: int = Field(20, ge=1)
    seed_offset: int = 0
    split: Literal["train", "eval"] = "train"
    level: int = Field(0, ge=0, le=4)


class KeygenTaskset(vf.Taskset[KeygenTask, KeygenTasksetConfig]):
    def load(self) -> list[KeygenTask]:
        if (
            self.config.split == "train"
            and self.config.seed_offset + self.config.num_tasks > EVAL_SEED_BASE
        ):
            raise ValueError("train split seed range reaches the eval range")
        seed_base = EVAL_SEED_BASE if self.config.split == "eval" else 0
        first_seed = seed_base + self.config.seed_offset
        tasks = []
        for seed in range(
            first_seed,
            first_seed + self.config.num_tasks,
        ):
            instance = generate(seed, self.config.level)
            artifact = "check.py" if instance.level == 0 else "check"
            how_to_run = (
                "Run it with `python3 check.py <name> <serial>`; it prints ACCEPTED or REJECTED."
                if instance.level == 0
                else "Run it with `./check <name> <serial>`; it prints ACCEPTED or REJECTED."
            )
            if instance.level == 1:
                how_to_run += " Its C source is in `check.c`."
            prompt = (
                f"A license checker is installed at {REPO_ROOT}/{artifact}. {how_to_run}\n"
                f"Example: the name `{instance.example_name}` has the serial "
                f"`{instance.example_serial}`.\n\n"
                f"Write {REPO_ROOT}/keygen.py defining `keygen(name: str) -> str` that "
                "returns a serial the checker accepts for any name of 3-16 ASCII "
                "letters and digits. A hidden test suite checks many names. Only "
                "edit `keygen.py`; do not modify or delete the provided files. "
                "Scratch files are allowed but are deleted before grading. "
                "Available tools include "
                "objdump, readelf, strings, gdb and python3."
            )
            data = KeygenData(
                id=f"keygen-l{instance.level}-{seed}",
                prompt=prompt,
                seed=seed,
                level=instance.level,
                files=instance.files,
                expected_files=instance.expected_files,
                protected_hashes=instance.protected_hashes,
                check_c_source=instance.check_c_source,
                reference_source=instance.reference_source,
                example_name=instance.example_name,
                example_serial=instance.example_serial,
                hidden_names=instance.hidden_names,
                image="rlvr-keygen:0.1",
                workdir=REPO_ROOT,
                network=vf.NetworkPolicyConfig(allow=[]),
                scoring=vf.ScoringConfig(mode="isolated"),
                artifacts=[vf.Artifact(source=REPO_ROOT)],
            )
            tasks.append(KeygenTask(data, self.config.task))
        return tasks
