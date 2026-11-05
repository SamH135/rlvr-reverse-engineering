"""Verifiers taskset for isolated grading of generated Python bugfixes."""

from __future__ import annotations

import asyncio
import json
import secrets
from importlib.resources import files
from typing import Any, Literal

import verifiers.v1 as vf
from pydantic import Field
from verifiers.v1.utils.artifacts import collect

from rlvr_coding_env.families.bugfix.generator import generate

REPO_ROOT = "/app/repo"
GRADER_ROOT = "/grader"
RUNNER_TIMEOUT_SECONDS = 20
MAX_RESULT_BYTES = 1_000_000


class BugfixData(vf.TaskData):
    seed: int
    level: Literal[1, 2]
    template_ids: list[str]
    mutation_ids: list[str]
    target_functions: list[str]
    files: dict[str, str]
    protected_hashes: dict[str, str]
    hidden_cases: list[list[object]]
    reference_source: str


class BugfixTask(vf.Task[BugfixData]):
    NEEDS_CONTAINER = True

    async def setup(self, trace: vf.Trace, runtime: vf.Runtime) -> None:
        for path, content in self.data.files.items():
            await runtime.write(f"{REPO_ROOT}/{path}", content.encode("utf-8"))

    async def stage_verifier(self, trace: vf.Trace, runtime: vf.Runtime) -> None:
        runner = (
            files("rlvr_coding_env.families.bugfix").joinpath("runner.py").read_bytes()
        )
        nonce = secrets.token_urlsafe(32)
        cases = {
            "nonce": nonce,
            "cases": self.data.hidden_cases,
        }
        self._grading_nonce = nonce
        await runtime.write(f"{GRADER_ROOT}/runner.py", runner)
        await runtime.write(
            f"{GRADER_ROOT}/cases.json",
            json.dumps(cases, allow_nan=False).encode("utf-8"),
        )
        await runtime.write(
            f"{GRADER_ROOT}/protected.json",
            json.dumps(self.data.protected_hashes, sort_keys=True).encode("utf-8"),
        )
        result = await runtime.run(["rm", "-f", f"{GRADER_ROOT}/result.json"], {})
        if result.exit_code:
            raise RuntimeError("could not clear the grader result file")

    async def _grading(self, runtime: vf.Runtime, trace: vf.Trace) -> dict[str, Any]:
        cached = trace.info.get("bugfix_grading")
        if cached is not None:
            return cached

        lock = getattr(self, "_grading_lock", None)
        if lock is None:
            lock = asyncio.Lock()
            self._grading_lock = lock
        async with lock:
            cached = trace.info.get("bugfix_grading")
            if cached is not None:
                return cached
            result = await self._compute_grading(runtime)
            trace.info["bugfix_grading"] = result
            return result

    async def _compute_grading(self, runtime: vf.Runtime) -> dict[str, Any]:
        scope_result = await runtime.run(
            [
                "python3",
                f"{GRADER_ROOT}/runner.py",
                "--scope",
                f"{GRADER_ROOT}/protected.json",
            ],
            {},
        )
        if scope_result.exit_code:
            raise RuntimeError("the trusted scope checker failed to run")
        try:
            scope_ok = json.loads(scope_result.stdout).get("scope_ok") is True
        except (json.JSONDecodeError, AttributeError):
            raise RuntimeError(
                "the trusted scope checker returned invalid output"
            ) from None

        result: dict[str, Any] = {
            "scope_ok": scope_ok,
            "hidden_pass_frac": 0.0,
            "visible_pass": 0.0,
            "runner_timeout": False,
            "runner_completed": False,
        }
        if scope_ok:
            command = (
                f"exec timeout --signal=KILL {RUNNER_TIMEOUT_SECONDS}s python3 "
                f"{GRADER_ROOT}/runner.py --run {GRADER_ROOT}/cases.json "
                f"{GRADER_ROOT}/result.json >/dev/null 2>&1"
            )
            hidden_run = await runtime.run(["sh", "-c", command], {})
            result["runner_timeout"] = hidden_run.exit_code in (124, 137)

            if not result["runner_timeout"]:
                exists = await runtime.run(
                    ["test", "-f", f"{GRADER_ROOT}/result.json"], {}
                )
                if exists.exit_code == 0:
                    size = await runtime.run(
                        ["sh", "-c", f"wc -c < {GRADER_ROOT}/result.json"], {}
                    )
                    try:
                        result_size = int(size.stdout.strip())
                    except ValueError:
                        result_size = MAX_RESULT_BYTES + 1
                    if size.exit_code == 0 and result_size <= MAX_RESULT_BYTES:
                        raw_result = await runtime.read(
                            f"{GRADER_ROOT}/result.json",
                            max_bytes=MAX_RESULT_BYTES,
                        )
                        try:
                            payload = json.loads(raw_result)
                        except (json.JSONDecodeError, UnicodeDecodeError):
                            payload = None
                        if (
                            isinstance(payload, dict)
                            and payload.get("nonce") == self._grading_nonce
                            and isinstance(payload.get("outputs"), list)
                            and len(payload["outputs"]) == len(self.data.hidden_cases)
                        ):
                            result["runner_completed"] = hidden_run.exit_code == 0
                            if result["runner_completed"]:
                                namespace: dict[str, object] = {}
                                exec(  # noqa: S102
                                    compile(
                                        self.data.reference_source,
                                        "<trusted-reference>",
                                        "exec",
                                    ),
                                    namespace,
                                )
                                expected = []
                                for function_name, args in self.data.hidden_cases:
                                    value = namespace[function_name](*args)
                                    json.dumps(value, allow_nan=False)
                                    expected.append({"ok": True, "value": value})
                                outputs = payload["outputs"]
                                result["hidden_pass_frac"] = sum(
                                    json.dumps(actual, sort_keys=True)
                                    == json.dumps(truth, sort_keys=True)
                                    for actual, truth in zip(
                                        outputs, expected, strict=True
                                    )
                                ) / len(expected)

            if not result["runner_timeout"]:
                visible_command = (
                    f"cd {REPO_ROOT} && exec env PYTHONPATH={REPO_ROOT} "
                    f"timeout --signal=KILL "
                    f"{RUNNER_TIMEOUT_SECONDS}s "
                    "python3 tests/test_visible.py >/dev/null 2>&1"
                )
                visible_run = await runtime.run(["sh", "-c", visible_command], {})
                if visible_run.exit_code in (124, 137):
                    result["runner_timeout"] = True
                else:
                    result["visible_pass"] = float(visible_run.exit_code == 0)

        return result

    @vf.metric
    async def scope_ok(self, runtime: vf.Runtime, trace: vf.Trace) -> float:
        return float((await self._grading(runtime, trace))["scope_ok"])

    @vf.metric
    async def hidden_pass_frac(self, runtime: vf.Runtime, trace: vf.Trace) -> float:
        return float((await self._grading(runtime, trace))["hidden_pass_frac"])

    @vf.metric
    async def visible_pass(self, runtime: vf.Runtime, trace: vf.Trace) -> float:
        return float((await self._grading(runtime, trace))["visible_pass"])

    @vf.metric
    async def runner_timeout(self, runtime: vf.Runtime, trace: vf.Trace) -> float:
        return float((await self._grading(runtime, trace))["runner_timeout"])

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
            f"{REPO_ROOT}/lib.py", self.data.reference_source.encode("utf-8")
        )
        await self.finalize(trace, runtime)
        trace.state.artifacts = await collect(
            runtime,
            self.data.artifacts,
            max_bytes=self.data.artifact_max_bytes,
        )
        await vf.grade_submission(self, trace, runtime)
        return trace.reward == 1.0


class BugfixTasksetConfig(vf.TasksetConfig):
    num_tasks: int = Field(20, ge=1)
    seed_offset: int = 0
    level: int = Field(1, ge=1, le=2)


class BugfixTaskset(vf.Taskset[BugfixTask, BugfixTasksetConfig]):
    def load(self) -> list[BugfixTask]:
        tasks = []
        for seed in range(
            self.config.seed_offset,
            self.config.seed_offset + self.config.num_tasks,
        ):
            instance = generate(seed, self.config.level)
            if instance.level == 1:
                prompt = (
                    f"Issue: Fix `{instance.target_functions[0]}` in `lib.py`. "
                    f"{instance.specs[0]}\n\n"
                    f"The visible test `{instance.visible_cases[0]['name']}` currently "
                    "fails. Fix the implementation so it matches the specification "
                    "and passes the visible test and the full hidden test suite.\n\n"
                    f"The repository is at {REPO_ROOT}. Only edit `lib.py`; do not "
                    "modify the tests or any other files."
                )
                task_id = f"bugfix-{seed}"
            else:
                first_function, second_function = instance.target_functions
                first_spec, second_spec = instance.specs
                prompt = (
                    "Issue: Users report that functions in `lib.py` do not always "
                    "follow their specifications:\n"
                    f"- `{first_function}`: {first_spec}\n"
                    f"- `{second_function}`: {second_spec}\n\n"
                    "The visible tests in `tests/test_visible.py` pass, but they do "
                    "not cover the reported failures. Find and fix every bug so each "
                    "function matches its specification on all inputs; a hidden test "
                    "suite checks both functions.\n\n"
                    f"The repository is at {REPO_ROOT}. Only edit `lib.py`; do not "
                    "modify the tests or any other files."
                )
                task_id = f"bugfix-l2-{seed}"
            data = BugfixData(
                id=task_id,
                prompt=prompt,
                seed=instance.seed,
                level=instance.level,
                template_ids=instance.template_ids,
                mutation_ids=instance.mutation_ids,
                target_functions=instance.target_functions,
                files=instance.files,
                protected_hashes=instance.protected_hashes,
                hidden_cases=instance.hidden_cases,
                reference_source=instance.reference_source,
                image="python:3.11-slim",
                workdir=REPO_ROOT,
                network=vf.NetworkPolicyConfig(allow=[]),
                scoring=vf.ScoringConfig(mode="isolated"),
                artifacts=[vf.Artifact(source=REPO_ROOT)],
            )
            tasks.append(BugfixTask(data, self.config.task))
        return tasks
