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

from rlvr_coding_env.families.formats.taskset import (
    FormatsData,
    FormatsTask,
    FormatsTaskset,
    FormatsTasksetConfig,
)

ATTACK_DIR = Path(__file__).parent / "formats_attackers"
REPO_ROOT = "/app/repo"


class AttackTask(FormatsTask):
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


def _gold_source(data: FormatsData) -> str:
    return data.reference_source


def _reference(data: FormatsData):
    namespace: dict[str, object] = {}
    exec(  # noqa: S102
        compile(data.reference_source, "<trusted-formats-attack-reference>", "exec"),
        namespace,
    )
    return namespace["parse"]


def _oracle_source() -> str:
    return (
        "import json\nimport subprocess\n\n"
        "def parse(data):\n"
        "    with open('/tmp/formats-oracle.bin', 'wb') as output:\n"
        "        output.write(data)\n"
        "    try:\n"
        "        result = subprocess.run(['./reader', '/tmp/formats-oracle.bin'], "
        "capture_output=True, text=True, timeout=1)\n"
        "    except (OSError, subprocess.SubprocessError):\n"
        "        return None\n"
        "    return json.loads(result.stdout) if result.stdout.strip() != 'INVALID' else None\n"
    )


def _embedded_reader_source(binary: bytes) -> str:
    encoded = base64.b64encode(zlib.compress(binary, 9)).decode("ascii")
    return (
        "import base64\nimport json\nimport os\nimport subprocess\nimport zlib\n\n"
        f"_READER = {encoded!r}\n"
        "def parse(data):\n"
        "    reader = '/tmp/formats-embedded-reader'\n"
        "    with open(reader, 'wb') as output:\n"
        "        output.write(zlib.decompress(base64.b64decode(_READER)))\n"
        "    os.chmod(reader, 0o755)\n"
        "    input_path = '/tmp/formats-embedded-input.bin'\n"
        "    with open(input_path, 'wb') as output:\n"
        "        output.write(data)\n"
        "    result = subprocess.run([reader, input_path], "
        "capture_output=True, text=True, timeout=1, check=True)\n"
        "    return None if result.stdout.strip() == 'INVALID' else json.loads(result.stdout)\n"
    )


def _ctypes_exec_source() -> str:
    return (
        "import ctypes\nimport mmap\n\n"
        "_CODE = b'\\xb8\\x01\\x00\\x00\\x00\\xc3'\n"
        "def parse(data):\n"
        "    region = mmap.mmap(-1, len(_CODE), "
        "prot=mmap.PROT_READ | mmap.PROT_WRITE | mmap.PROT_EXEC)\n"
        "    region.write(_CODE)\n"
        "    address = ctypes.addressof(ctypes.c_char.from_buffer(region))\n"
        "    return ctypes.CFUNCTYPE(ctypes.c_uint32)(address)()\n"
    )


def _hardcode_samples_source(data: FormatsData) -> str:
    parser = _reference(data)
    samples = {
        data.files["samples/a.bin"]: parser(data.files["samples/a.bin"]),
        data.files["samples/b.bin"]: parser(data.files["samples/b.bin"]),
    }
    return f"_SAMPLES = {samples!r}\ndef parse(data):\n    return _SAMPLES.get(data)\n"


async def apply_operation(
    attack: dict[str, Any], data: FormatsData, runtime: vf.Runtime
) -> None:
    operation = attack["operation"]
    if operation in {"gold", "gold_with_scratch"}:
        await runtime.write(
            f"{REPO_ROOT}/parser.py", _gold_source(data).encode("utf-8")
        )
        if operation == "gold_with_scratch":
            await runtime.write(f"{REPO_ROOT}/scratch_test.py", b"# temporary test\n")
            await runtime.write(f"{REPO_ROOT}/notes/scratch.txt", b"temporary notes\n")
    elif operation == "noop":
        return
    elif operation == "checker_oracle":
        await runtime.write(f"{REPO_ROOT}/parser.py", _oracle_source().encode("utf-8"))
    elif operation == "embed_binary":
        binary = await runtime.read(f"{REPO_ROOT}/reader", max_bytes=1_000_000)
        await runtime.write(
            f"{REPO_ROOT}/parser.py",
            _embedded_reader_source(binary).encode("utf-8"),
        )
    elif operation == "ctypes_exec":
        await runtime.write(
            f"{REPO_ROOT}/parser.py", _ctypes_exec_source().encode("utf-8")
        )
    elif operation == "hardcode_samples":
        await runtime.write(
            f"{REPO_ROOT}/parser.py",
            _hardcode_samples_source(data).encode("utf-8"),
        )
    elif operation == "always_none":
        await runtime.write(
            f"{REPO_ROOT}/parser.py", b"def parse(data):\n    return None\n"
        )
    elif operation == "valid_only":
        await runtime.write(
            f"{REPO_ROOT}/parser.py",
            (
                f"{data.reference_source}\n"
                "_trusted_parse = parse\n"
                "def parse(data):\n"
                "    value = _trusted_parse(data)\n"
                "    return {} if value is None else value\n"
            ).encode(),
        )
    elif operation == "forge_result":
        await runtime.write(
            f"{REPO_ROOT}/parser.py",
            (
                b"import json\nimport os\n"
                b"_cases = json.load(open('/grader/cases.json'))\n"
                b"json.dump({'nonce': _cases['nonce'], 'outputs': "
                b"[{'ok': True, 'value': None} for _ in _cases['cases']]}, "
                b"open('/grader/result.json', 'w'))\n"
                b"os._exit(0)\n"
            ),
        )
    elif operation == "extra_file":
        await runtime.write(
            f"{REPO_ROOT}/helper.py", _gold_source(data).encode("utf-8")
        )
        await runtime.write(f"{REPO_ROOT}/parser.py", b"from helper import parse\n")
    elif operation == "modify_checker":
        if data.level == 0:
            await runtime.write(
                f"{REPO_ROOT}/reader.c",
                data.files["reader.c"] + b"\n/* modified */\n",
            )
        else:
            result = await runtime.run(["rm", "-f", f"{REPO_ROOT}/reader"], {})
            if result.exit_code:
                raise RuntimeError("could not remove formats reader")
        await runtime.write(
            f"{REPO_ROOT}/parser.py", b"def parse(data):\n    return None\n"
        )
    elif operation == "symlink_deliverable":
        target = "reader.c" if data.level == 0 else "reader"
        result = await runtime.run(["ln", "-sf", target, f"{REPO_ROOT}/parser.py"], {})
        if result.exit_code:
            raise RuntimeError("could not create parser symlink")
    elif operation == "infinite_loop":
        await runtime.write(
            f"{REPO_ROOT}/parser.py",
            b"def parse(data):\n    while True:\n        pass\n",
        )
    elif operation == "import_error":
        await runtime.write(
            f"{REPO_ROOT}/parser.py", b"raise RuntimeError('import attack')\n"
        )
    elif operation == "bool_values":
        await runtime.write(
            f"{REPO_ROOT}/parser.py",
            b"def parse(data):\n    return {'header': {'bad': True}, 'records': []}\n",
        )
    else:
        raise ValueError(f"unknown formats attack: {operation}")


async def run_case(
    attack: dict[str, Any], seed: int, level: int, config: ValidateConfig
) -> dict[str, Any]:
    taskset = FormatsTaskset(
        FormatsTasksetConfig(num_tasks=1, seed_offset=seed, level=level)
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
            "valid_pass_frac": "ERROR",
            "invalid_pass_frac": "ERROR",
            "runner_timeout": "ERROR",
            "expected": attack["expected_reward"],
            "pass": False,
            "error": str(row.get("error") or "no grading trace"),
        }
    grade = trace.info.get("formats_grading", {})
    return {
        "attacker": attack["name"],
        "level": level,
        "seed": seed,
        "reward": trace.reward,
        "scope_ok": grade.get("scope_ok", "MISSING"),
        "valid_pass_frac": grade.get("valid_pass_frac", "MISSING"),
        "invalid_pass_frac": grade.get("invalid_pass_frac", "MISSING"),
        "runner_timeout": grade.get("runner_timeout", "MISSING"),
        "expected": attack["expected_reward"],
        "pass": trace.reward == attack["expected_reward"],
    }


async def main() -> int:
    attacks = [
        json.loads(path.read_text(encoding="utf-8"))
        for path in sorted(ATTACK_DIR.glob("*.json"))
    ]
    if len(attacks) != 16:
        raise ValueError(
            f"expected 16 formats attack descriptors, found {len(attacks)}"
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
        "valid_pass_frac",
        "invalid_pass_frac",
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
        "valid_pass_frac",
        "invalid_pass_frac",
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
