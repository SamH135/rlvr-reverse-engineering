"""Verifiers taskset for isolated binary-format reverse engineering."""

from __future__ import annotations

import asyncio
import json
import secrets
from importlib.resources import files
from typing import Any, Literal

import verifiers.v1 as vf
from pydantic import ConfigDict, Field
from verifiers.v1.utils.artifacts import collect

from rlvr_coding_env.families.common import EVAL_SEED_BASE
from rlvr_coding_env.families.common.grading import grade_function
from rlvr_coding_env.families.formats.generator import generate

REPO_ROOT = "/app/repo"
GRADER_ROOT = "/grader"


class FormatsData(vf.TaskData):
    model_config = ConfigDict(ser_json_bytes="hex", val_json_bytes="hex")

    seed: int
    level: int
    files: dict[str, bytes]
    expected_files: list[str]
    protected_hashes: dict[str, str]
    c_source: str
    reference_source: str
    sample_a_hex: str
    hidden_files_hex: list[str]
    valid_count: int


class FormatsTask(vf.Task[FormatsData]):
    NEEDS_CONTAINER = True

    async def setup(self, trace: vf.Trace, runtime: vf.Runtime) -> None:
        await runtime.run(["mkdir", "-p", f"{REPO_ROOT}/samples"], {})
        for path, content in self.data.files.items():
            await runtime.write(f"{REPO_ROOT}/{path}", content)
        await runtime.run(["rm", "-rf", "/tmp/formats-build"], {})
        await runtime.run(["mkdir", "-p", "/tmp/formats-build"], {})
        await runtime.write(
            "/tmp/formats-build/reader.c", self.data.c_source.encode("utf-8")
        )
        optimization = "-O0" if self.data.level <= 1 else "-O2"
        compiled = await runtime.run(
            [
                "gcc",
                optimization,
                "/tmp/formats-build/reader.c",
                "-o",
                "/tmp/formats-build/reader",
            ],
            {},
        )
        if compiled.exit_code:
            raise RuntimeError("could not compile the formats reader")
        if self.data.level >= 2:
            stripped = await runtime.run(["strip", "/tmp/formats-build/reader"], {})
            if stripped.exit_code:
                raise RuntimeError("could not strip the formats reader")
        copied = await runtime.run(
            ["cp", "/tmp/formats-build/reader", f"{REPO_ROOT}/reader"], {}
        )
        if copied.exit_code:
            raise RuntimeError("could not install the formats reader")
        removed = await runtime.run(["rm", "-rf", "/tmp/formats-build"], {})
        if removed.exit_code:
            raise RuntimeError("could not remove temporary formats source")

    async def stage_verifier(self, trace: vf.Trace, runtime: vf.Runtime) -> None:
        runner = (
            files("rlvr_coding_env.families.common").joinpath("runner.py").read_bytes()
        )
        nonce = secrets.token_urlsafe(32)
        cases = {
            "nonce": nonce,
            "deliverable": "parser.py",
            "function_name": "parse",
            "return_type": "json",
            "arg_decode": "hex",
            "cases": [
                [case_hex]
                for case_hex in [self.data.sample_a_hex, *self.data.hidden_files_hex]
            ],
        }
        protected = {
            "deliverable": "parser.py",
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
        cached = trace.info.get("formats_grading")
        if cached is not None:
            return cached
        lock = getattr(self, "_grading_lock", None)
        if lock is None:
            lock = asyncio.Lock()
            self._grading_lock = lock
        async with lock:
            cached = trace.info.get("formats_grading")
            if cached is not None:
                return cached
            result = await self._compute_grading(runtime)
            trace.info["formats_grading"] = result
            return result

    async def _compute_grading(self, runtime: vf.Runtime) -> dict[str, Any]:
        namespace: dict[str, object] = {}
        exec(  # noqa: S102
            compile(
                self.data.reference_source,
                "<trusted-formats-reference>",
                "exec",
            ),
            namespace,
        )
        parser = namespace["parse"]
        expected = [
            {
                "ok": True,
                "value": parser(bytes.fromhex(case_hex)),  # type: ignore[operator]
            }
            for case_hex in [self.data.sample_a_hex, *self.data.hidden_files_hex]
        ]
        grade = await grade_function(
            runtime,
            self._grading_nonce,
            expected,
            include_case_passes=True,
        )
        passed = grade.get("case_passes", [])[1:]
        valid = passed[: self.data.valid_count]
        invalid = passed[self.data.valid_count :]
        grade["valid_pass_frac"] = sum(valid) / len(valid) if valid else 0.0
        grade["invalid_pass_frac"] = sum(invalid) / len(invalid) if invalid else 0.0
        return grade

    @vf.metric
    async def scope_ok(self, runtime: vf.Runtime, trace: vf.Trace) -> float:
        return float((await self._grading(runtime, trace))["scope_ok"])

    @vf.metric
    async def hidden_pass_frac(self, runtime: vf.Runtime, trace: vf.Trace) -> float:
        return float((await self._grading(runtime, trace))["hidden_pass_frac"])

    @vf.metric
    async def valid_pass_frac(self, runtime: vf.Runtime, trace: vf.Trace) -> float:
        return float((await self._grading(runtime, trace))["valid_pass_frac"])

    @vf.metric
    async def invalid_pass_frac(self, runtime: vf.Runtime, trace: vf.Trace) -> float:
        return float((await self._grading(runtime, trace))["invalid_pass_frac"])

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
            and grade["valid_pass_frac"] == 1.0
            and grade["invalid_pass_frac"] == 1.0
        )

    async def validate(self, runtime: vf.Runtime, trace: vf.Trace) -> bool:
        await runtime.write(
            f"{REPO_ROOT}/parser.py", self.data.reference_source.encode("utf-8")
        )
        await self.finalize(trace, runtime)
        trace.state.artifacts = await collect(
            runtime,
            self.data.artifacts,
            max_bytes=self.data.artifact_max_bytes,
        )
        await vf.grade_submission(self, trace, runtime)
        return trace.reward == 1.0


class FormatsTasksetConfig(vf.TasksetConfig):
    num_tasks: int = Field(20, ge=1)
    seed_offset: int = 0
    split: Literal["train", "eval"] = "train"
    level: int = Field(0, ge=0, le=4)


class FormatsTaskset(vf.Taskset[FormatsTask, FormatsTasksetConfig]):
    def load(self) -> list[FormatsTask]:
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
            source_note = (
                " The reader's C source is in `reader.c`."
                if instance.level == 0
                else ""
            )
            prompt = (
                f"A compiled binary reader is installed at {REPO_ROOT}/reader."
                f"{source_note} Run it as `./reader samples/a.bin`; it prints canonical "
                "JSON, or `INVALID` for malformed files. Two valid sample files are in "
                f"`{REPO_ROOT}/samples/`.\n"
                f"Example: `samples/a.bin` prints `{instance.sample_a_output}`.\n\n"
                f"Write {REPO_ROOT}/parser.py defining "
                "`parse(data: bytes) -> dict | None` to match the reader, including "
                "rejecting invalid files. A hidden test suite checks many valid and "
                "malformed files. Only edit `parser.py`; do not modify or delete the "
                "provided files. Scratch files are allowed but are deleted before grading."
            )
            data = FormatsData(
                id=f"formats-l{instance.level}-{seed}",
                prompt=prompt,
                seed=seed,
                level=instance.level,
                files=instance.files,
                expected_files=instance.expected_files,
                protected_hashes=instance.protected_hashes,
                c_source=instance.c_source,
                reference_source=instance.reference_source,
                sample_a_hex=instance.sample_a.hex(),
                hidden_files_hex=[data.hex() for data in instance.hidden_files],
                valid_count=instance.valid_count,
                image="rlvr-keygen:0.1",
                workdir=REPO_ROOT,
                network=vf.NetworkPolicyConfig(allow=[]),
                scoring=vf.ScoringConfig(mode="isolated"),
                artifacts=[vf.Artifact(source=REPO_ROOT)],
            )
            tasks.append(FormatsTask(data, self.config.task))
        return tasks
