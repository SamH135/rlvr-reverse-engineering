"""Host-side generated-program sweep and Docker validation report updater.

Per task: structural shape checks, a degenerate-output check (constant hidden
output fails), and C-vs-reference agreement on every case.
"""

from __future__ import annotations

import argparse
import multiprocessing
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from rlvr_coding_env.families.common import EVAL_SEED_BASE
from rlvr_coding_env.families.decompile.generator import generate as generate_decompile
from rlvr_coding_env.families.formats.generator import canonical_json
from rlvr_coding_env.families.formats.generator import generate as generate_formats
from rlvr_coding_env.families.keygen.generator import generate as generate_keygen

FAMILIES = ("keygen", "decompile", "formats")
REPORT_PATH = Path(__file__).with_name("REPORT.md")
MAX_FAILURE_DETAILS = 5
PROCESS_TIMEOUT_SECONDS = 10


@dataclass
class TaskResult:
    family: str
    level: int
    seed: int
    disasm_lines: int | None = None
    failure_count: int = 0
    failure_details: list[str] = field(default_factory=list)


def _fail(result: TaskResult, detail: str) -> None:
    result.failure_count += 1
    if len(result.failure_details) < MAX_FAILURE_DETAILS:
        result.failure_details.append(detail)


def _run(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        capture_output=True,
        check=False,
        text=True,
        timeout=PROCESS_TIMEOUT_SECONDS,
    )


def _compile(
    source_text: str,
    binary: Path,
    optimization: str,
    *,
    strip_binary: bool,
) -> None:
    source = binary.with_suffix(".c")
    source.write_text(source_text, encoding="utf-8")
    subprocess.run(
        ["gcc", optimization, str(source), "-o", str(binary)],
        capture_output=True,
        check=True,
        text=True,
        timeout=120,
    )
    if strip_binary:
        subprocess.run(
            ["strip", str(binary)],
            capture_output=True,
            check=True,
            text=True,
            timeout=30,
        )


def _disasm_lines(binary: Path) -> int:
    output = subprocess.run(
        ["objdump", "-d", str(binary)],
        capture_output=True,
        check=True,
        text=True,
        timeout=30,
    ).stdout
    return len(output.splitlines())


def _namespace(source: str, label: str) -> dict[str, Any]:
    namespace: dict[str, Any] = {}
    exec(compile(source, label, "exec"), namespace)  # noqa: S102
    return namespace


def _record_process_mismatch(
    result: TaskResult,
    label: str,
    process: subprocess.CompletedProcess[str],
    expected_stdout: str,
    expected_returncode: int,
) -> None:
    if process.stdout != expected_stdout or process.returncode != expected_returncode:
        _fail(
            result,
            f"{label}: expected rc={expected_returncode}, "
            f"stdout={expected_stdout!r}; got rc={process.returncode}, "
            f"stdout={process.stdout[:160]!r}, stderr={process.stderr[:160]!r}",
        )


def _check_keygen(result: TaskResult, directory: Path) -> None:
    instance = generate_keygen(result.seed, result.level)
    if (
        len(instance.hidden_names) != 50
        or len(set(instance.hidden_names)) != len(instance.hidden_names)
        or instance.example_name in instance.hidden_names
    ):
        _fail(result, "hidden names are not 50 unique names separate from the example")

    reference = _namespace(instance.reference_source, "<seed-sweep-keygen-reference>")[
        "serial"
    ]
    if result.level == 0:
        checker = directory / "check.py"
        checker.write_text(instance.files["check.py"], encoding="utf-8")
        command_prefix = [sys.executable, str(checker)]
        result.disasm_lines = None
    else:
        binary = directory / "check"
        optimization = "-O0" if result.level <= 2 else "-O2"
        _compile(
            instance.check_c_source,
            binary,
            optimization,
            strip_binary=result.level >= 3,
        )
        command_prefix = [str(binary)]
        result.disasm_lines = _disasm_lines(binary)

    names = [instance.example_name, *instance.hidden_names]
    if len({reference(name) for name in instance.hidden_names}) <= 1:
        _fail(result, "degenerate: constant serial over all hidden names")
    if instance.example_serial != reference(instance.example_name):
        _fail(result, "visible example serial differs from the trusted reference")
    for name in names:
        serial = reference(name)
        if not isinstance(serial, str):
            _fail(result, f"trusted serial for {name!r} is not a string")
            continue
        process = _run([*command_prefix, name, serial])
        _record_process_mismatch(
            result,
            f"checker acceptance for {name!r}",
            process,
            "ACCEPTED\n",
            0,
        )

    wrong_name = instance.hidden_names[0]
    expected_serial = reference(wrong_name)
    corrupt_serial = ("0" if expected_serial[0] != "0" else "1") + expected_serial[1:]
    process = _run([*command_prefix, wrong_name, corrupt_serial])
    _record_process_mismatch(
        result,
        f"checker rejection for corrupted serial of {wrong_name!r}",
        process,
        "REJECTED\n",
        1,
    )


def _check_decompile(result: TaskResult, directory: Path) -> None:
    instance = generate_decompile(result.seed, result.level)
    hidden = instance.hidden_inputs
    if (
        len(hidden) != 50
        or len({tuple(values) for values in hidden}) != len(hidden)
        or instance.example_input in hidden
    ):
        _fail(
            result, "hidden inputs are not 50 unique inputs separate from the example"
        )
    if (
        [] not in hidden
        or not any(len(values) == 1 for values in hidden)
        or [0, 0xFFFFFFFF] not in hidden
        or not any(len(values) == 12 for values in hidden)
    ):
        _fail(result, "hidden inputs omit required list-shape coverage")

    reference = _namespace(
        instance.reference_source, "<seed-sweep-decompile-reference>"
    )["f"]
    binary = directory / "prog"
    optimization = "-O0" if result.level <= 1 else "-O2"
    _compile(
        instance.c_source,
        binary,
        optimization,
        strip_binary=result.level >= 2,
    )
    result.disasm_lines = _disasm_lines(binary)

    if len({reference(xs) for xs in hidden}) <= 1:
        _fail(result, "degenerate: constant output over all hidden inputs")
    example_output = reference(instance.example_input)
    if example_output != instance.example_output:
        _fail(result, "visible example output differs from the trusted reference")
    for label, values in [
        ("visible example", instance.example_input),
        *[(f"hidden input {index}", xs) for index, xs in enumerate(hidden)],
    ]:
        expected = reference(values)
        if type(expected) is not int or not 0 <= expected <= 0xFFFFFFFF:
            _fail(result, f"{label} trusted output is not a uint32 int")
            continue
        process = _run([str(binary), *(str(value) for value in values)])
        try:
            actual = int(process.stdout.strip())
        except ValueError:
            _fail(
                result,
                f"{label}: binary output is not an integer: {process.stdout[:160]!r}",
            )
            continue
        if process.returncode != 0 or actual != expected:
            _fail(
                result,
                f"{label}: expected {expected}, got rc={process.returncode}, "
                f"stdout={process.stdout[:160]!r}",
            )


def _check_formats(result: TaskResult, directory: Path) -> None:
    instance = generate_formats(result.seed, result.level)
    hidden = instance.hidden_files
    sample_files = {
        instance.files["samples/a.bin"],
        instance.files["samples/b.bin"],
    }
    if (
        len(hidden) != 50
        or len(set(hidden)) != len(hidden)
        or set(hidden) & sample_files
    ):
        _fail(result, "hidden files are not 50 unique files separate from the samples")
    if instance.valid_count != 38 or len(hidden) - instance.valid_count != 12:
        _fail(result, "hidden files do not contain 38 valid and 12 malformed cases")

    reference = _namespace(instance.reference_source, "<seed-sweep-formats-reference>")[
        "parse"
    ]
    binary = directory / "reader"
    optimization = "-O0" if result.level <= 1 else "-O2"
    _compile(
        instance.c_source,
        binary,
        optimization,
        strip_binary=result.level >= 2,
    )
    result.disasm_lines = _disasm_lines(binary)
    input_path = directory / "input.bin"

    if (
        len(
            {
                canonical_json(reference(data))
                for data in hidden[: instance.valid_count]
            }
        )
        <= 1
    ):
        _fail(result, "degenerate: constant parse output over valid hidden files")
    sample_reference = reference(instance.sample_a)
    if sample_reference is None or instance.sample_a_output != canonical_json(
        sample_reference
    ):
        _fail(result, "visible sample output differs from the canonical reference")
    input_path.write_bytes(instance.sample_a)
    sample_process = _run([str(binary), str(input_path)])
    if sample_reference is not None:
        _record_process_mismatch(
            result,
            "visible sample reader output",
            sample_process,
            canonical_json(sample_reference) + "\n",
            0,
        )

    for index, data in enumerate(hidden):
        expected = reference(data)
        is_valid = index < instance.valid_count
        if is_valid and expected is None:
            _fail(
                result,
                f"hidden file {index} is marked valid but reference returns None",
            )
        if not is_valid and expected is not None:
            _fail(
                result,
                f"hidden file {index} is malformed but reference returns a value",
            )
        input_path.write_bytes(data)
        process = _run([str(binary), str(input_path)])
        if expected is None:
            if process.stdout != "INVALID\n" or process.returncode == 0:
                _fail(
                    result,
                    f"malformed hidden file {index}: expected INVALID, got "
                    f"rc={process.returncode}, stdout={process.stdout[:160]!r}",
                )
        else:
            _record_process_mismatch(
                result,
                f"valid hidden file {index}",
                process,
                canonical_json(expected) + "\n",
                0,
            )


def _check_task(job: tuple[str, int, int]) -> TaskResult:
    family, level, seed = job
    result = TaskResult(family=family, level=level, seed=seed)
    try:
        with tempfile.TemporaryDirectory(prefix="rlvr-seed-sweep-") as temp_dir:
            directory = Path(temp_dir)
            if family == "keygen":
                _check_keygen(result, directory)
            elif family == "decompile":
                _check_decompile(result, directory)
            else:
                _check_formats(result, directory)
    except Exception as error:  # noqa: BLE001 - capture each task's sweep failure
        _fail(result, f"{type(error).__name__}: {error}")
    return result


def _format_runtime(seconds: float) -> str:
    minutes, remaining = divmod(seconds, 60)
    return f"{int(minutes)}m {remaining:.1f}s ({seconds:.1f}s)"


def _write_sweep_report(results: list[TaskResult], duration: float) -> None:
    rows = []
    failures = []
    for family in FAMILIES:
        for level in range(5):
            cell = [
                result
                for result in results
                if result.family == family and result.level == level
            ]
            disassembly = [
                result.disasm_lines
                for result in cell
                if result.disasm_lines is not None
            ]
            median = "n/a" if not disassembly else f"{statistics.median(disassembly):g}"
            failed_tasks = sum(result.failure_count > 0 for result in cell)
            rows.append(
                f"| {family} | {level} | {len(cell)} | {failed_tasks} | {median} |"
            )
            failures.extend(result for result in cell if result.failure_count > 0)

    lines = [
        "# Multi-seed QC report",
        "",
        "Host-side generated-program checks; no Docker runtime or model was used.",
        (
            "Train seeds: 0–99; eval seeds: 1,000,000–1,000,019. "
            "Each family/level cell covers 120 tasks."
        ),
        f"Sweep runtime: {_format_runtime(duration)}.",
        "",
        "| Family | Level | Tasks checked | Failed tasks | Median `objdump -d` lines |",
        "| --- | ---: | ---: | ---: | ---: |",
        *rows,
        "",
        (
            "Failures count tasks with one or more failed checks. Keygen L0 has no "
            "provided binary, so its disassembly count is n/a."
        ),
        "",
        "## Failure details",
        "",
    ]
    if failures:
        for result in failures:
            lines.append(
                f"- {result.family} L{result.level}, seed {result.seed}: "
                f"{result.failure_count} failed check(s)."
            )
            lines.extend(f"  - {detail}" for detail in result.failure_details)
    else:
        lines.append("No failures.")
    lines.extend(
        [
            "",
            "## Docker gold/no-op validation",
            "",
            "Not recorded yet.",
            "",
        ]
    )
    REPORT_PATH.write_text("\n".join(lines), encoding="utf-8")


def _update_docker_report(raw_results: list[list[str]]) -> int:
    expected = {
        (family, level, "train")
        for family in FAMILIES
        for level in (range(7) if family != "formats" else range(5))
    } | {(family, level, "eval") for family in FAMILIES for level in (0, 4)}
    parsed: dict[tuple[str, int, str], tuple[int, int, int]] = {}
    for family, raw_level, split, raw_tasks, raw_gold, raw_noop in raw_results:
        try:
            level, tasks, gold, noop = map(
                int, (raw_level, raw_tasks, raw_gold, raw_noop)
            )
        except ValueError as error:
            raise ValueError(f"invalid Docker result row: {raw_results!r}") from error
        key = (family, level, split)
        if key not in expected or key in parsed:
            raise ValueError(f"unexpected or duplicate Docker result row: {key}")
        expected_tasks = 5 if split == "train" else 3
        if tasks != expected_tasks:
            raise ValueError(f"{key} must report {expected_tasks} tasks")
        parsed[key] = (tasks, gold, noop)
    if set(parsed) != expected:
        missing = sorted(expected - set(parsed))
        raise ValueError(f"missing Docker validation rows: {missing}")

    lines = [
        "## Docker gold/no-op validation",
        "",
        "| Family | Level | Split | Tasks | Gold valid | No-op valid |",
        "| --- | ---: | --- | ---: | ---: | ---: |",
    ]
    all_valid = True
    for family in FAMILIES:
        for level in range(7) if family != "formats" else range(5):
            for split in ("train",):
                tasks, gold, noop = parsed[(family, level, split)]
                lines.append(
                    f"| {family} | {level} | {split} | {tasks} | {gold} | {noop} |"
                )
                all_valid &= gold == tasks and noop == tasks
        for level in (0, 4):
            tasks, gold, noop = parsed[(family, level, "eval")]
            lines.append(f"| {family} | {level} | eval | {tasks} | {gold} | {noop} |")
            all_valid &= gold == tasks and noop == tasks
    lines.extend(
        [
            "",
            (
                "All gold and no-op validations were valid."
                if all_valid
                else "One or more gold/no-op validations were not fully valid."
            ),
            "",
        ]
    )
    if not REPORT_PATH.exists():
        raise FileNotFoundError(f"seed sweep report not found: {REPORT_PATH}")
    report = REPORT_PATH.read_text(encoding="utf-8")
    prefix, separator, _ = report.partition("\n## Docker gold/no-op validation")
    if not separator:
        raise ValueError("seed sweep report has no Docker validation section")
    REPORT_PATH.write_text(
        prefix + "\n\n" + "\n".join(lines),
        encoding="utf-8",
    )
    return 0 if all_valid else 1


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--docker-result",
        action="append",
        nargs=6,
        metavar=("FAMILY", "LEVEL", "SPLIT", "TASKS", "GOLD_VALID", "NOOP_VALID"),
        help="update the report with one completed Docker validation result",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    if args.docker_result:
        return _update_docker_report(args.docker_result)

    missing = [
        tool for tool in ("gcc", "strip", "objdump") if shutil.which(tool) is None
    ]
    if missing:
        raise RuntimeError(f"required host tools are missing: {', '.join(missing)}")
    jobs = [
        (family, level, seed)
        for family in FAMILIES
        for level in range(5)
        for seed in [*range(100), *range(EVAL_SEED_BASE, EVAL_SEED_BASE + 20)]
    ]
    started = time.monotonic()
    results = []
    with multiprocessing.Pool(processes=4) as pool:
        for index, result in enumerate(
            pool.imap_unordered(_check_task, jobs, chunksize=1),
            start=1,
        ):
            results.append(result)
            if index % 100 == 0:
                print(f"Checked {index}/{len(jobs)} tasks", flush=True)
    duration = time.monotonic() - started
    results.sort(key=lambda item: (FAMILIES.index(item.family), item.level, item.seed))
    _write_sweep_report(results, duration)
    failed_tasks = [result for result in results if result.failure_count]
    print(
        f"Seed sweep checked {len(results)} tasks in {_format_runtime(duration)}; "
        f"{len(failed_tasks)} tasks failed."
    )
    print(f"Report: {REPORT_PATH}")
    for result in failed_tasks:
        print(
            f"FAIL {result.family} L{result.level} seed {result.seed}: "
            + "; ".join(result.failure_details)
        )
    return int(bool(failed_tasks))


if __name__ == "__main__":
    raise SystemExit(main())
