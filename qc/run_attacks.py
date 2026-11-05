from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import verifiers.v1 as vf
from verifiers.v1.cli.validate import _run_check
from verifiers.v1.configs.agent import TimeoutConfig
from verifiers.v1.configs.cli.validate import ValidateConfig
from verifiers.v1.utils.artifacts import collect

from rlvr_coding_env.families.bugfix.generator import BugfixInstance, generate
from rlvr_coding_env.families.bugfix.taskset import (
    BugfixTask,
    BugfixTaskset,
    BugfixTasksetConfig,
)

ATTACK_DIR = Path(__file__).parent / "attackers"
NETWORK_PROBE = """
import urllib.error
import urllib.request
try:
    urllib.request.urlopen("https://example.com", timeout=5)
except urllib.error.HTTPError:
    print("reachable")
except Exception:
    print("blocked")
else:
    print("reachable")
"""


class NetworkProbeTask(vf.Task):
    NEEDS_CONTAINER = True

    @vf.reward(weight=1.0)
    async def policy_held(self, trace: vf.Trace, runtime: vf.Runtime) -> float:
        return float(trace.info.get("agent_network_probe") == "blocked")


class NetworkProbeHarness(vf.Harness):
    async def launch(self, ctx, trace, runtime, endpoint, secret, mcp_urls, data):
        probe = await runtime.run(["python3", "-c", NETWORK_PROBE], {})
        trace.info["agent_network_probe"] = probe.stdout.strip() or "no result"
        return await runtime.run(["true"], {})


class AttackTask(BugfixTask):
    async def validate(self, trace: vf.Trace, runtime: vf.Runtime) -> bool:
        self.last_trace = trace
        instance: BugfixInstance = self.instance
        await apply_operation(self.attack, instance, runtime)
        await self.finalize(trace, runtime)
        trace.state.artifacts = await collect(
            runtime,
            self.data.artifacts,
            max_bytes=self.data.artifact_max_bytes,
        )
        await vf.grade_submission(self, trace, runtime)
        self.last_trace = trace
        return trace.reward == self.attack["expected_reward"]


async def write_lib(runtime: vf.Runtime, source: str) -> None:
    await runtime.write("/app/repo/lib.py", source.encode("utf-8"))


def forged_result_source(instance: BugfixInstance) -> str:
    return (
        instance.files["lib.py"]
        + "\nimport json as _json\nimport os as _os\n"
        + "_cases = _json.load(open('/grader/cases.json'))\n"
        + f"_function = globals()[{instance.target_function!r}]\n"
        + "_outputs = []\n"
        + "for _args in _cases['inputs']:\n"
        + "    try:\n"
        + "        _value = _function(*_args)\n"
        + "        _json.dumps(_value, allow_nan=False)\n"
        + "        _outputs.append({'ok': True, 'value': _value})\n"
        + "    except BaseException as _error:\n"
        + "        _outputs.append({'ok': False, 'error': type(_error).__name__})\n"
        + "with open('/grader/result.json', 'w') as _result_file:\n"
        + "    _json.dump({'nonce': _cases['nonce'], 'outputs': _outputs}, "
        "_result_file, allow_nan=False)\n" + "_os._exit(0)\n"
    )


def visible_special_case_source(instance: BugfixInstance) -> str:
    cases = [(case["args"], case["expected"]) for case in instance.visible_cases]
    return (
        f"def {instance.target_function}(*args):\n"
        f"    for _inputs, _expected in {cases!r}:\n"
        "        if list(args) == _inputs:\n"
        "            return _expected\n"
        "    return None\n"
    )


def type_confusion_source(instance: BugfixInstance) -> str:
    reference = instance.reference_source.replace(
        f"def {instance.target_function}(", "def _bugfix_reference(", 1
    )
    return (
        f"{reference.rstrip()}\n\n"
        f"def {instance.target_function}(*args):\n"
        "    return float(_bugfix_reference(*args))\n"
    )


def memory_bomb_source(instance: BugfixInstance) -> str:
    return (
        "_memory_bomb_done = False\n\n"
        f"def {instance.target_function}(*args):\n"
        "    global _memory_bomb_done\n"
        "    if not _memory_bomb_done:\n"
        "        _memory_bomb_done = True\n"
        "        _blocks = []\n"
        "        for _ in range(64):\n"
        "            _blocks.append(bytearray(32 * 1024 * 1024))\n"
        "    return None\n"
    )


async def apply_operation(
    attack: dict[str, Any], instance: BugfixInstance, runtime: vf.Runtime
) -> None:
    operation = attack["operation"]
    if operation == "gold":
        await write_lib(runtime, instance.reference_source)
    elif operation == "edit_visible_test":
        await write_lib(runtime, instance.reference_source)
        await runtime.write("/app/repo/tests/test_visible.py", b"pass\n")
    elif operation == "delete_tests":
        result = await runtime.run(["rm", "-rf", "/app/repo/tests"], {})
        if result.exit_code:
            raise RuntimeError("could not delete visible tests in solver workspace")
    elif operation == "add_extra_file":
        await runtime.write("/app/repo/conftest.py", b"EXTRA = True\n")
    elif operation == "symlink_lib":
        await runtime.run(["rm", "-f", "/app/repo/lib.py"], {})
        result = await runtime.run(
            ["ln", "-s", "tests/test_visible.py", "/app/repo/lib.py"], {}
        )
        if result.exit_code:
            raise RuntimeError("could not replace lib.py with a symlink")
    elif operation == "fake_stdout_exit":
        await write_lib(
            runtime,
            'import os\nprint(\'{"nonce":"forged","outputs":[]}\')\nos._exit(0)\n',
        )
    elif operation == "forge_result_file":
        await write_lib(runtime, forged_result_source(instance))
    elif operation == "infinite_loop":
        await write_lib(
            runtime,
            f"def {instance.target_function}(*args):\n    while True:\n        pass\n",
        )
    elif operation == "memory_bomb":
        await write_lib(runtime, memory_bomb_source(instance))
    elif operation == "raise_at_import":
        await write_lib(runtime, "raise RuntimeError('import attack')\n")
    elif operation == "special_case_visible":
        await write_lib(runtime, visible_special_case_source(instance))
    elif operation == "type_confusion":
        await write_lib(runtime, type_confusion_source(instance))
    elif operation != "noop":
        raise ValueError(f"unknown attack operation: {operation}")


def load_attacks() -> list[dict[str, Any]]:
    attacks = [
        json.loads(path.read_text(encoding="utf-8"))
        for path in sorted(ATTACK_DIR.glob("*.json"))
    ]
    if len(attacks) != 13:
        raise ValueError(f"expected 13 attack descriptors, found {len(attacks)}")
    for attack in attacks:
        templates = {generate(seed).template_id for seed in attack["seeds"]}
        if len(attack["seeds"]) != 2 or len(templates) != 2:
            raise ValueError(
                f"{attack['name']} must cover two seeds with different templates"
            )
    return attacks


async def run_case(
    attack: dict[str, Any], seed: int, validate_config: ValidateConfig
) -> dict[str, Any]:
    taskset = BugfixTaskset(BugfixTasksetConfig(num_tasks=1, seed_offset=seed))
    base_task = next(iter(taskset))
    task = AttackTask(base_task.data, base_task.config)
    task.attack = attack
    task.instance = generate(seed)
    task.last_trace = None
    row = await _run_check(task, validate_config, "gold")
    trace = task.last_trace
    expected = float(attack["expected_reward"])
    error = row.get("error")
    if error is not None or trace is None:
        return {
            "attacker": attack["name"],
            "seed": seed,
            "reward": "ERROR",
            "scope_ok": "ERROR",
            "hidden_pass_frac": "ERROR",
            "runner_timeout": "ERROR",
            "expected": expected,
            "pass": False,
            "error": str(error or "validation produced no trace"),
        }

    grading = trace.info.get("bugfix_grading", {})
    reward = trace.reward
    return {
        "attacker": attack["name"],
        "seed": seed,
        "reward": reward,
        "scope_ok": grading.get("scope_ok", "MISSING"),
        "hidden_pass_frac": grading.get("hidden_pass_frac", "MISSING"),
        "runner_timeout": grading.get("runner_timeout", "MISSING"),
        "expected": expected,
        "pass": reward == expected,
    }


def display(value: object, digits: int = 3) -> str:
    if isinstance(value, bool):
        return str(int(value))
    return f"{value:.{digits}f}" if isinstance(value, (float, int)) else str(value)


async def verify_agent_network_policy() -> str:
    task = NetworkProbeTask(
        vf.TaskData(
            prompt="Run the configured network-policy probe.",
            image="python:3.11-slim",
            workdir="/app/repo",
            network=vf.NetworkPolicyConfig(allow=[]),
        )
    )
    config = vf.AgentConfig(
        model="unused",
        runtime=vf.DockerConfig(allow=[], memory=4.0),
        timeout=TimeoutConfig(setup=180, finalize=30, scoring=120),
    )
    async with vf.Agent(config) as agent:
        agent.harness = NetworkProbeHarness(vf.HarnessConfig())
        trace = await agent.run(task)
    outcome = trace.info.get("agent_network_probe", "no result")
    print(f"Agent network policy probe: {outcome}")
    return str(outcome)


async def main() -> int:
    attacks = load_attacks()
    validate_config = ValidateConfig(runtime=vf.DockerConfig(allow=[], memory=4.0))
    network_probe = await verify_agent_network_policy()
    rows = []
    for attack in attacks:
        for seed in attack["seeds"]:
            rows.append(await run_case(attack, seed, validate_config))

    headers = (
        "attacker",
        "seed",
        "reward",
        "scope_ok",
        "hidden_pass_frac",
        "runner_timeout",
        "expected",
        "PASS/FAIL",
    )
    widths = (22, 4, 8, 9, 17, 14, 8, 9)
    print(
        " ".join(
            header.ljust(width) for header, width in zip(headers, widths, strict=True)
        )
    )
    for row in rows:
        values = (
            row["attacker"],
            str(row["seed"]),
            display(row["reward"]),
            display(row["scope_ok"]),
            display(row["hidden_pass_frac"]),
            display(row["runner_timeout"]),
            display(row["expected"], 1),
            "PASS" if row["pass"] else "FAIL",
        )
        print(
            " ".join(
                value.ljust(width) for value, width in zip(values, widths, strict=True)
            )
        )
        if row.get("error"):
            print(f"  error: {row['error']}")

    failures = [row for row in rows if not row["pass"]]
    print(f"Attack checks: {len(rows) - len(failures)}/{len(rows)} passed")
    return int(bool(failures) or network_probe != "blocked")


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
