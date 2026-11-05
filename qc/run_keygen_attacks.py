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

from rlvr_coding_env.families.keygen.taskset import (
    KeygenData,
    KeygenTask,
    KeygenTaskset,
    KeygenTasksetConfig,
)

ATTACK_DIR = Path(__file__).parent / "keygen_attackers"
REPO_ROOT = "/app/repo"


class AttackTask(KeygenTask):
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


def _reference_keygen(data: KeygenData) -> str:
    return (
        f"{data.reference_source}\n"
        "def keygen(name: str) -> str:\n"
        "    return serial(name)\n"
    )


def _fixed_keygen(name: str, serial: str) -> str:
    return (
        f"def keygen(value):\n"
        f"    return {serial!r} if value == {name!r} else '0000-0000'\n"
    )


def _oracle_keygen(data: KeygenData) -> str:
    command = (
        ["python3", f"{REPO_ROOT}/check.py"]
        if data.level == 0
        else [f"{REPO_ROOT}/check"]
    )
    return (
        "import subprocess\n\n"
        f"_COMMAND = {command!r}\n"
        "def keygen(name):\n"
        "    for value in range(16):\n"
        "        serial = f'{value:04X}-0000'\n"
        "        try:\n"
        "            result = subprocess.run(_COMMAND + [name, serial], "
        "capture_output=True, text=True, timeout=1)\n"
        "        except (OSError, subprocess.SubprocessError):\n"
        "            break\n"
        "        if result.stdout.strip() == 'ACCEPTED':\n"
        "            return serial\n"
        "    return '0000-0000'\n"
    )


def _embedded_checker_keygen(data: KeygenData, checker: bytes) -> str:
    encoded = base64.b64encode(zlib.compress(checker, 9)).decode("ascii")
    command = (
        ["python3", "/tmp/keygen-embedded-checker"]
        if data.level == 0
        else ["/tmp/keygen-embedded-checker"]
    )
    return (
        "import base64\nimport os\nimport subprocess\nimport zlib\n\n"
        f"_CHECKER = {encoded!r}\n"
        f"_COMMAND = {command!r}\n"
        "def keygen(name):\n"
        "    path = '/tmp/keygen-embedded-checker'\n"
        "    with open(path, 'wb') as output:\n"
        "        output.write(zlib.decompress(base64.b64decode(_CHECKER)))\n"
        "    os.chmod(path, 0o755)\n"
        "    serial = "
        f"{data.example_serial!r}\n"
        "    try:\n"
        "        result = subprocess.run(_COMMAND + [name, serial], "
        "capture_output=True, text=True, timeout=1)\n"
        "    except (OSError, subprocess.SubprocessError):\n"
        "        return '0000-0000'\n"
        "    return serial if result.stdout.strip() == 'ACCEPTED' else '0000-0000'\n"
    )


async def apply_operation(
    attack: dict[str, Any], data: KeygenData, runtime: vf.Runtime
) -> None:
    operation = attack["operation"]
    if operation == "gold":
        await runtime.write(f"{REPO_ROOT}/keygen.py", _reference_keygen(data).encode())
    elif operation == "noop":
        return
    elif operation == "hardcode_example":
        await runtime.write(
            f"{REPO_ROOT}/keygen.py",
            _fixed_keygen(data.example_name, data.example_serial).encode(),
        )
    elif operation == "constant_serial":
        await runtime.write(
            f"{REPO_ROOT}/keygen.py", b"def keygen(name):\n    return '0000-0000'\n"
        )
    elif operation == "checker_oracle":
        await runtime.write(f"{REPO_ROOT}/keygen.py", _oracle_keygen(data).encode())
    elif operation == "embed_checker":
        checker_path = (
            f"{REPO_ROOT}/check.py" if data.level == 0 else f"{REPO_ROOT}/check"
        )
        checker = await runtime.read(checker_path, max_bytes=1_000_000)
        await runtime.write(
            f"{REPO_ROOT}/keygen.py",
            _embedded_checker_keygen(data, checker).encode(),
        )
    elif operation == "forge_result":
        await runtime.write(
            f"{REPO_ROOT}/keygen.py",
            (
                b"import json\nimport os\n"
                b"_cases = json.load(open('/grader/cases.json'))\n"
                b"json.dump({'nonce': _cases['nonce'], 'outputs': "
                b"[{'ok': True, 'value': '0000-0000'} for _ in _cases['names']]}, "
                b"open('/grader/result.json', 'w'))\n"
                b"os._exit(0)\n"
            ),
        )
    elif operation == "modify_checker":
        if data.level == 0:
            await runtime.write(
                f"{REPO_ROOT}/check.py",
                (data.files["check.py"] + "\n# modified\n").encode(),
            )
        elif data.level == 1:
            await runtime.write(
                f"{REPO_ROOT}/check.c",
                (data.files["check.c"] + "\n/* modified */\n").encode(),
            )
        else:
            result = await runtime.run(["rm", "-f", f"{REPO_ROOT}/check"], {})
            if result.exit_code:
                raise RuntimeError("could not remove checker binary")
        await runtime.write(
            f"{REPO_ROOT}/keygen.py", b"def keygen(name):\n    return '0000-0000'\n"
        )
    elif operation == "extra_file":
        await runtime.write(
            f"{REPO_ROOT}/keygen.py", b"def keygen(name):\n    return ''\n"
        )
        await runtime.write(f"{REPO_ROOT}/extra.txt", b"extra\n")
    elif operation == "symlink_keygen":
        target = "check.py" if data.level == 0 else "check"
        result = await runtime.run(["ln", "-s", target, f"{REPO_ROOT}/keygen.py"], {})
        if result.exit_code:
            raise RuntimeError("could not create keygen symlink")
    elif operation == "infinite_loop":
        await runtime.write(
            f"{REPO_ROOT}/keygen.py",
            b"def keygen(name):\n    while True:\n        pass\n",
        )
    elif operation == "import_error":
        await runtime.write(
            f"{REPO_ROOT}/keygen.py", b"raise RuntimeError('import attack')\n"
        )
    elif operation == "non_string":
        await runtime.write(
            f"{REPO_ROOT}/keygen.py", b"def keygen(name):\n    return 1\n"
        )
    else:
        raise ValueError(f"unknown keygen attack: {operation}")


async def run_case(
    attack: dict[str, Any], seed: int, level: int, config: ValidateConfig
) -> dict[str, Any]:
    taskset = KeygenTaskset(
        KeygenTasksetConfig(num_tasks=1, seed_offset=seed, level=level)
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
    grade = trace.info.get("keygen_grading", {})
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
    if len(attacks) != 13:
        raise ValueError(f"expected 13 keygen attack descriptors, found {len(attacks)}")
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
    widths = {
        key: max(
            len(label),
            *(len(str(row[key])) for row in rows),
        )
        for key, label in zip(
            (
                "attacker",
                "level",
                "seed",
                "reward",
                "scope_ok",
                "hidden_pass_frac",
                "runner_timeout",
                "expected",
                "pass",
            ),
            headers,
            strict=True,
        )
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
            label.ljust(widths[key]) for key, label in zip(widths, headers, strict=True)
        )
    )
    for row in rows:
        if "error" in row:
            print(
                f"ERROR {row['attacker']} level={row['level']} "
                f"seed={row['seed']}: {row['error']}"
            )
        print(" ".join(display(key, row[key]).ljust(widths[key]) for key in widths))
    passed = sum(bool(row["pass"]) for row in rows)
    print(f"Attack checks: {passed}/{len(rows)} passed")
    return 0 if passed == len(rows) else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
