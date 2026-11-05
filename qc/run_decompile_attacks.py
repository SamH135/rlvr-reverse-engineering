from __future__ import annotations

import asyncio
import base64
import json
import zlib
from pathlib import Path
from typing import Any

import verifiers.v1 as vf
from verifiers.v1.cli.validate import _run_check
from verifiers.v1.configs.cli.validate import ValidateConfig
from verifiers.v1.utils.artifacts import collect

from rlvr_coding_env.families.decompile.taskset import (
    DecompileData,
    DecompileTask,
    DecompileTaskset,
    DecompileTasksetConfig,
)

ATTACK_DIR = Path(__file__).parent / "decompile_attackers"
REPO_ROOT = "/app/repo"


class AttackTask(DecompileTask):
    async def validate(self, trace: vf.Trace, runtime: vf.Runtime) -> bool:
        await apply_operation(self.attack, self.data, runtime)
        await self.finalize(trace, runtime)
        trace.state.artifacts = await collect(
            runtime,
            self.data.artifacts,
            max_bytes=self.data.artifact_max_bytes,
        )
        await vf.grade_submission(self, trace, runtime)
        self.last_trace = trace
        return trace.reward == self.attack["expected_reward"]


def _gold_source(data: DecompileData) -> str:
    return data.reference_source


def _hardcode_source(data: DecompileData) -> str:
    return (
        f"def f(xs):\n"
        f"    return {data.example_output} if xs == {data.example_input!r} else 0\n"
    )


def _oracle_source() -> str:
    return (
        "import subprocess\n\n"
        "def f(xs):\n"
        "    try:\n"
        "        result = subprocess.run(['/app/repo/prog', *map(str, xs)], "
        "capture_output=True, text=True, timeout=1)\n"
        "    except (OSError, subprocess.SubprocessError):\n"
        "        return 0\n"
        "    return int(result.stdout.strip())\n"
    )


def _embedded_source(binary: bytes) -> str:
    encoded = base64.b64encode(zlib.compress(binary, 9)).decode("ascii")
    return (
        "import base64\nimport os\nimport subprocess\nimport zlib\n\n"
        f"_PROGRAM = {encoded!r}\n"
        "_PATH = '/tmp/decompile-embedded-prog'\n"
        "def f(xs):\n"
        "    if not os.path.exists(_PATH):\n"
        "        with open(_PATH, 'wb') as output:\n"
        "            output.write(zlib.decompress(base64.b64decode(_PROGRAM)))\n"
        "        os.chmod(_PATH, 0o755)\n"
        "    result = subprocess.run([_PATH, *map(str, xs)], "
        "capture_output=True, text=True, timeout=1, check=True)\n"
        "    return int(result.stdout.strip())\n"
    )


async def apply_operation(
    attack: dict[str, Any], data: DecompileData, runtime: vf.Runtime
) -> None:
    operation = attack["operation"]
    if operation == "gold":
        await runtime.write(
            f"{REPO_ROOT}/solution.py", _gold_source(data).encode("utf-8")
        )
    elif operation == "noop":
        return
    elif operation == "constant_output":
        await runtime.write(f"{REPO_ROOT}/solution.py", b"def f(xs):\n    return 0\n")
    elif operation == "embed_binary":
        binary = await runtime.read(f"{REPO_ROOT}/prog", max_bytes=1_000_000)
        await runtime.write(
            f"{REPO_ROOT}/solution.py", _embedded_source(binary).encode("utf-8")
        )
    elif operation == "hardcode_example":
        await runtime.write(
            f"{REPO_ROOT}/solution.py", _hardcode_source(data).encode("utf-8")
        )
    elif operation == "checker_oracle":
        await runtime.write(
            f"{REPO_ROOT}/solution.py", _oracle_source().encode("utf-8")
        )
    elif operation == "forge_result":
        await runtime.write(
            f"{REPO_ROOT}/solution.py",
            (
                b"import json\nimport os\n"
                b"_cases = json.load(open('/grader/cases.json'))\n"
                b"json.dump({'nonce': _cases['nonce'], 'outputs': "
                b"[{'ok': True, 'value': -1} for _ in _cases['cases']]}, "
                b"open('/grader/result.json', 'w'))\n"
                b"os._exit(0)\n"
            ),
        )
    elif operation == "extra_file":
        await runtime.write(f"{REPO_ROOT}/solution.py", b"def f(xs):\n    return 0\n")
        await runtime.write(f"{REPO_ROOT}/extra.txt", b"extra\n")
    elif operation == "modify_checker":
        if data.level == 0:
            await runtime.write(
                f"{REPO_ROOT}/prog.c",
                (data.files["prog.c"] + "\n/* modified */\n").encode(),
            )
        else:
            result = await runtime.run(["rm", "-f", f"{REPO_ROOT}/prog"], {})
            if result.exit_code:
                raise RuntimeError("could not remove decompile program")
        await runtime.write(f"{REPO_ROOT}/solution.py", b"def f(xs):\n    return 0\n")
    elif operation == "symlink_deliverable":
        target = "prog.c" if data.level == 0 else "prog"
        result = await runtime.run(["ln", "-s", target, f"{REPO_ROOT}/solution.py"], {})
        if result.exit_code:
            raise RuntimeError("could not create solution symlink")
    elif operation == "infinite_loop":
        await runtime.write(
            f"{REPO_ROOT}/solution.py",
            b"def f(xs):\n    while True:\n        pass\n",
        )
    elif operation == "import_error":
        await runtime.write(
            f"{REPO_ROOT}/solution.py", b"raise RuntimeError('import attack')\n"
        )
    elif operation == "non_int_output":
        await runtime.write(f"{REPO_ROOT}/solution.py", b"def f(xs):\n    return 1.0\n")
    elif operation == "bool_output":
        await runtime.write(
            f"{REPO_ROOT}/solution.py", b"def f(xs):\n    return True\n"
        )
    else:
        raise ValueError(f"unknown decompile attack: {operation}")


async def run_case(
    attack: dict[str, Any], seed: int, level: int, config: ValidateConfig
) -> dict[str, Any]:
    taskset = DecompileTaskset(
        DecompileTasksetConfig(num_tasks=1, seed_offset=seed, level=level)
    )
    base_task = next(iter(taskset))
    task = AttackTask(base_task.data, base_task.config)
    task.attack = attack
    row = await _run_check(task, config, "gold")
    trace = getattr(task, "last_trace", None)
    if row.get("error") is not None or trace is None:
        return {
            "attacker": attack["name"],
            "level": level,
            "seed": seed,
            "reward": "ERROR",
            "scope_ok": "ERROR",
            "hidden_pass_frac": "ERROR",
            "runner_timeout": "ERROR",
            "expected": attack["expected_reward"],
            "pass": False,
            "error": str(row.get("error") or "no grading trace"),
        }
    grade = trace.info.get("decompile_grading", {})
    return {
        "attacker": attack["name"],
        "level": level,
        "seed": seed,
        "reward": trace.reward,
        "scope_ok": grade.get("scope_ok", "MISSING"),
        "hidden_pass_frac": grade.get("hidden_pass_frac", "MISSING"),
        "runner_timeout": grade.get("runner_timeout", "MISSING"),
        "expected": attack["expected_reward"],
        "pass": trace.reward == attack["expected_reward"],
    }


async def main() -> int:
    attacks = [
        json.loads(path.read_text(encoding="utf-8"))
        for path in sorted(ATTACK_DIR.glob("*.json"))
    ]
    if len(attacks) != 14:
        raise ValueError(
            f"expected 14 decompile attack descriptors, found {len(attacks)}"
        )
    config = ValidateConfig(runtime=vf.DockerConfig(allow=[], memory=4.0))
    rows = []
    for level in (0, 3):
        for attack in attacks:
            for seed in attack["seeds"]:
                rows.append(await run_case(attack, seed, level, config))

    headers = (
        "attacker",
        "level",
        "seed",
        "reward",
        "scope_ok",
        "hidden_pass_frac",
        "runner_timeout",
        "expected",
        "PASS/FAIL",
    )
    keys = (
        "attacker",
        "level",
        "seed",
        "reward",
        "scope_ok",
        "hidden_pass_frac",
        "runner_timeout",
        "expected",
        "pass",
    )
    widths = {
        key: max(len(label), *(len(str(row[key])) for row in rows))
        for key, label in zip(keys, headers, strict=True)
    }

    def display(key: str, value: object) -> str:
        if key == "pass":
            return "PASS" if value else "FAIL"
        if isinstance(value, bool):
            return "1" if value else "0"
        if isinstance(value, float):
            return f"{value:.3f}"
        return str(value)

    print(
        " ".join(
            label.ljust(widths[key]) for key, label in zip(keys, headers, strict=True)
        )
    )
    for row in rows:
        if "error" in row:
            print(
                f"ERROR {row['attacker']} level={row['level']} "
                f"seed={row['seed']}: {row['error']}"
            )
        print(" ".join(display(key, row[key]).ljust(widths[key]) for key in keys))
    passed = sum(bool(row["pass"]) for row in rows)
    print(f"Attack checks: {passed}/{len(rows)} passed")
    return 0 if passed == len(rows) else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
