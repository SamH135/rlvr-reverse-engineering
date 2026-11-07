"""Trusted isolated function grading entry point."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import shutil
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(os.environ.get("RLVR_REPO_ROOT", "/app/repo"))
MAX_DELIVERABLE_BYTES = 16 * 1024
MAX_RESULT_BYTES = 1_000_000


def _valid_json_value(value: Any) -> bool:
    if value is None or isinstance(value, str) or type(value) is int:
        return True
    if isinstance(value, list):
        return all(_valid_json_value(item) for item in value)
    if isinstance(value, dict):
        return all(
            type(key) is str and _valid_json_value(item) for key, item in value.items()
        )
    return False


def _clean_submission(deliverable: str) -> bool:
    valid = True
    for path in REPO_ROOT.iterdir():
        if path.name == deliverable:
            continue
        try:
            if path.is_symlink() or path.is_file():
                path.unlink()
            elif path.is_dir():
                shutil.rmtree(path)
            else:
                path.unlink()
        except OSError:
            valid = False
    return valid


def check_scope(protected_path: Path) -> dict[str, Any]:
    protected = json.loads(protected_path.read_text())
    deliverable = protected["deliverable"]
    actual: dict[str, str] = {}
    symlink_found = False
    for current, directories, files in os.walk(REPO_ROOT, followlinks=False):
        current_path = Path(current)
        kept_directories = []
        for name in directories:
            path = current_path / name
            if name == "__pycache__":
                continue
            if path.is_symlink():
                symlink_found = True
                continue
            kept_directories.append(name)
        directories[:] = kept_directories
        for name in files:
            path = current_path / name
            if "__pycache__" in path.relative_to(REPO_ROOT).parts:
                continue
            if path.is_symlink() or not path.is_file():
                symlink_found = True
                continue
            actual[path.relative_to(REPO_ROOT).as_posix()] = hashlib.sha256(
                path.read_bytes()
            ).hexdigest()

    expected = set(protected["expected_files"]) | {deliverable}
    hashes = protected["hashes"]
    deliverable_path = REPO_ROOT / deliverable
    try:
        deliverable_size_ok = (
            deliverable_path.is_file()
            and deliverable_path.stat().st_size <= MAX_DELIVERABLE_BYTES
        )
    except OSError:
        deliverable_size_ok = False
    # Extra files are removed before the candidate is imported.
    valid = (
        not symlink_found
        and expected <= set(actual)
        and deliverable_size_ok
        and all(actual.get(path) == digest for path, digest in hashes.items())
    )
    cleaned = _clean_submission(deliverable)
    return {"scope_ok": valid and cleaned}


def _write_result(result_path: Path, payload: dict[str, object]) -> None:
    encoded = json.dumps(payload, allow_nan=False).encode()
    if len(encoded) > MAX_RESULT_BYTES:
        encoded = json.dumps(
            {"nonce": payload["nonce"], "outputs": None, "error": "too_large"}
        ).encode()
    temporary = result_path.with_suffix(".tmp")
    temporary.write_bytes(encoded)
    os.replace(temporary, result_path)


def run_hidden(cases_path: Path, result_path: Path) -> None:
    payload = json.loads(cases_path.read_text())
    cases = payload["cases"]
    outputs = []

    def _deny(event: str, args: tuple[Any, ...]) -> None:
        if event in {
            "subprocess.Popen",
            "os.system",
            "os.exec",
            "os.posix_spawn",
            "os.spawn",
            "os.fork",
            "os.forkpty",
            "os.vfork",
            "pty.spawn",
            "mmap.__new__",
        } or event.startswith("ctypes."):
            raise PermissionError(f"audit event denied: {event}")
        if event == "import" and args[0].split(".")[0] in {
            "ctypes",
            "_ctypes",
            "cffi",
            "mmap",
            "_posixsubprocess",
        }:
            raise PermissionError(f"audit event denied: {event}")
        if event == "open" and isinstance(args[0], (str, bytes, os.PathLike)):
            path = Path(os.fsdecode(args[0]))
            proc = Path("/proc")
            absolute = Path(os.path.abspath(path))
            resolved = path.resolve()
            if (
                absolute == proc
                or proc in absolute.parents
                or resolved == proc
                or proc in resolved.parents
            ):
                raise PermissionError(f"audit event denied: {event}")
        if (
            event == "object.__setattr__"
            and len(args) > 1
            and args[1] in {"__code__", "__closure__", "__defaults__"}
        ):
            raise PermissionError(f"audit event denied: {event}")

    sys.addaudithook(_deny)
    try:
        spec = importlib.util.spec_from_file_location(
            f"_{Path(payload['deliverable']).stem}_submission",
            REPO_ROOT / payload["deliverable"],
        )
        if spec is None or spec.loader is None:
            raise ImportError("could not load submission")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    except BaseException as error:  # noqa: BLE001
        outputs = [{"ok": False, "error": type(error).__name__} for _ in cases]
    else:
        for arguments in cases:
            try:
                if payload.get("arg_decode") == "hex":
                    arguments = [bytes.fromhex(argument) for argument in arguments]
                function = getattr(module, payload["function_name"])
                value = function(*arguments)
                if payload["return_type"] == "str":
                    valid_value = isinstance(value, str)
                elif payload["return_type"] == "uint32":
                    valid_value = type(value) is int and 0 <= value < 2**32
                elif payload["return_type"] == "json":
                    valid_value = value is None or (
                        isinstance(value, dict) and _valid_json_value(value)
                    )
                else:
                    raise ValueError("unknown return type")
                if not valid_value:
                    raise TypeError("submission returned an invalid value")
                encoded = json.dumps(
                    value, sort_keys=True, separators=(",", ":"), allow_nan=False
                )
                if payload["return_type"] == "json":
                    json.loads(encoded)
                outputs.append({"ok": True, "value": value})
            except BaseException as error:  # noqa: BLE001
                outputs.append({"ok": False, "error": type(error).__name__})
    _write_result(result_path, {"nonce": payload["nonce"], "outputs": outputs})


def main(argv: list[str] | None = None) -> int:
    arguments = sys.argv[1:] if argv is None else argv
    if len(arguments) == 2 and arguments[0] == "--scope":
        print(json.dumps(check_scope(Path(arguments[1]))))
        return 0
    if len(arguments) == 3 and arguments[0] == "--run":
        run_hidden(Path(arguments[1]), Path(arguments[2]))
        return 0
    print("usage: runner.py --scope protected.json | --run cases.json result.json")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
