"""Trusted keygen grading entry point."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import shutil
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path("/app/repo")
MAX_KEYGEN_BYTES = 16 * 1024
MAX_RESULT_BYTES = 1_000_000


def _clean_submission() -> bool:
    valid = True
    for path in REPO_ROOT.iterdir():
        if path.name == "keygen.py":
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

    expected = set(protected["expected_files"]) | {"keygen.py"}
    hashes = protected["hashes"]
    keygen_path = REPO_ROOT / "keygen.py"
    try:
        keygen_size_ok = (
            keygen_path.is_file() and keygen_path.stat().st_size <= MAX_KEYGEN_BYTES
        )
    except OSError:
        keygen_size_ok = False
    valid = (
        not symlink_found
        and set(actual) == expected
        and keygen_size_ok
        and all(actual.get(path) == digest for path, digest in hashes.items())
    )
    return {"scope_ok": valid and _clean_submission()}


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
    names = payload["names"]
    outputs = []
    try:
        spec = importlib.util.spec_from_file_location(
            "_keygen_submission", REPO_ROOT / "keygen.py"
        )
        if spec is None or spec.loader is None:
            raise ImportError("could not load keygen.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        function = module.keygen
    except BaseException as error:  # noqa: BLE001
        outputs = [{"ok": False, "error": type(error).__name__} for _ in names]
    else:
        for name in names:
            try:
                value = function(name)
                if not isinstance(value, str):
                    raise TypeError("keygen must return str")
                json.dumps(value, allow_nan=False)
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
