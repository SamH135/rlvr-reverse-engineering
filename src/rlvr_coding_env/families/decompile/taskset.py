"""Verifiers taskset for isolated compiled-program reverse engineering."""

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
from rlvr_coding_env.families.decompile.generator import generate

REPO_ROOT = "/app/repo"
GRADER_ROOT = "/grader"


class DecompileData(vf.TaskData):
    seed: int
    level: int
    files: dict[str, str]
    expected_files: list[str]
    protected_hashes: dict[str, str]
    c_source: str
    reference_source: str
    example_input: list[int]
    example_output: int
    hidden_inputs: list[list[int]]


class DecompileTask(vf.Task[DecompileData]):
    NEEDS_CONTAINER = True

    async def setup(self, trace: vf.Trace, runtime: vf.Runtime) -> None:
        for path, content in self.data.files.items():
            await runtime.write(f"{REPO_ROOT}/{path}", content.encode("utf-8"))
        await runtime.run(["rm", "-rf", "/tmp/decompile-build"], {})
        await runtime.run(["mkdir", "-p", "/tmp/decompile-build"], {})
        await runtime.write(
            "/tmp/decompile-build/prog.c", self.data.c_source.encode("utf-8")
        )
        optimization = "-O0" if self.data.level <= 1 else "-O2"
        compiled = await runtime.run(
            [
                "gcc",
                optimization,
                "/tmp/decompile-build/prog.c",
                "-o",
                "/tmp/decompile-build/prog",
            ],
            {},
        )
        if compiled.exit_code:
            raise RuntimeError("could not compile the decompile program")
        if self.data.level >= 2:
            stripped = await runtime.run(["strip", "/tmp/decompile-build/prog"], {})
            if stripped.exit_code:
                raise RuntimeError("could not strip the decompile program")
        copied = await runtime.run(
            ["cp", "/tmp/decompile-build/prog", f"{REPO_ROOT}/prog"], {}
        )
        if copied.exit_code:
            raise RuntimeError("could not install the decompile program")
        removed = await runtime.run(["rm", "-rf", "/tmp/decompile-build"], {})
        if removed.exit_code:
            raise RuntimeError("could not remove temporary decompile source")
        await runtime.write(
            f"{REPO_ROOT}/solution.py",
            b"def f(xs: list[int]) -> int:\n    raise NotImplementedError\n",
        )

    async def stage_verifier(self, trace: vf.Trace, runtime: vf.Runtime) -> None:
        runner = (
            files("rlvr_coding_env.families.common").joinpath("runner.py").read_bytes()
        )
        nonce = secrets.token_urlsafe(32)
        cases = {
            "nonce": nonce,
            "deliverable": "solution.py",
            "function_name": "f",
            "return_type": "uint32",
            "cases": [
                [xs] for xs in [self.data.example_input, *self.data.hidden_inputs]
            ],
        }
        protected = {
            "deliverable": "solution.py",
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
        cached = trace.info.get("decompile_grading")
        if cached is not None:
            return cached
        lock = getattr(self, "_grading_lock", None)
        if lock is None:
            lock = asyncio.Lock()
            self._grading_lock = lock
        async with lock:
            cached = trace.info.get("decompile_grading")
            if cached is not None:
                return cached
            result = await self._compute_grading(runtime)
            trace.info["decompile_grading"] = result
            return result

    async def _compute_grading(self, runtime: vf.Runtime) -> dict[str, Any]:
        namespace: dict[str, object] = {}
        exec(  # noqa: S102
            compile(
                self.data.reference_source,
                "<trusted-decompile-reference>",
                "exec",
            ),
            namespace,
        )
        reference = namespace["f"]
        expected = [{"ok": True, "value": reference(self.data.example_input)}] + [
            {"ok": True, "value": reference(xs)} for xs in self.data.hidden_inputs
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
        await runtime.write(
            f"{REPO_ROOT}/solution.py", self.data.reference_source.encode("utf-8")
        )
        await self.finalize(trace, runtime)
        trace.state.artifacts = await collect(
            runtime,
            self.data.artifacts,
            max_bytes=self.data.artifact_max_bytes,
        )
        await vf.grade_submission(self, trace, runtime)
        return trace.reward == 1.0


class DecompileTasksetConfig(vf.TasksetConfig):
    num_tasks: int = Field(20, ge=1)
    seed_offset: int = 0
    split: Literal["train", "eval"] = "train"
    level: int = Field(0, ge=0, le=6)


class DecompileTaskset(vf.Taskset[DecompileTask, DecompileTasksetConfig]):
    def load(self) -> list[DecompileTask]:
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
            source_note = " Its C source is in `prog.c`." if instance.level == 0 else ""
            prompt = (
                f"A compiled program is installed at {REPO_ROOT}/prog."
                f"{source_note} Run it as `./prog [x1 x2 ...]`; for an empty "
                f"list, run `./prog` with no arguments. It prints one decimal "
                "uint32 result.\n"
                f"Example input: `{instance.example_input}`; output: "
                f"`{instance.example_output}`.\n\n"
                f"Edit the stub at {REPO_ROOT}/solution.py (it already exists; you "
                "may also overwrite it with bash) defining `f(xs: list[int]) -> int` "
                "to match the program for any list of 0-12 uint32 values. A hidden "
                "test suite checks many inputs. Only edit `solution.py`; do not "
                "modify or delete the provided files. Scratch files are allowed but "
                "are deleted before grading."
            )
            data = DecompileData(
                id=f"decompile-l{instance.level}-{seed}",
                prompt=prompt,
                seed=seed,
                level=instance.level,
                files=instance.files,
                expected_files=instance.expected_files,
                protected_hashes=instance.protected_hashes,
                c_source=instance.c_source,
                reference_source=instance.reference_source,
                example_input=instance.example_input,
                example_output=instance.example_output,
                hidden_inputs=instance.hidden_inputs,
                image="rlvr-keygen:0.1",
                workdir=REPO_ROOT,
                network=vf.NetworkPolicyConfig(allow=[]),
                scoring=vf.ScoringConfig(mode="isolated"),
                artifacts=[vf.Artifact(source=REPO_ROOT)],
            )
            tasks.append(DecompileTask(data, self.config.task))
        return tasks
