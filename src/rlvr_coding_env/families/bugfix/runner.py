"""Trusted grader entry point; agent code is only imported in ``--run`` mode."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import sys
from pathlib import Path
from typing import Any

CACHE_DIRS = {"__pycache__", ".pytest_cache"}
LIB_PATH = Path("/app/repo/lib.py")
MAX_RESULT_BYTES = 1_000_000


def check_scope(protected_path: Path) -> dict[str, Any]:
    protected = json.loads(protected_path.read_text())
    root = Path("/app/repo")
    actual: dict[str, str] = {}
    symlink_found = False
    for current, directories, files in os.walk(root, followlinks=False):
        current_path = Path(current)
        retained = []
        for name in directories:
            path = current_path / name
            if name in CACHE_DIRS:
                continue
            if path.is_symlink():
                symlink_found = True
                continue
            retained.append(name)
        directories[:] = retained
        for name in files:
            path = current_path / name
            if any(part in CACHE_DIRS for part in path.relative_to(root).parts):
                continue
            if path.is_symlink() or not path.is_file():
                symlink_found = True
                continue
            relative = path.relative_to(root).as_posix()
            actual[relative] = hashlib.sha256(path.read_bytes()).hexdigest()

    expected_paths = set(protected)
    permitted_paths = expected_paths | {"lib.py"}
    valid = (
        not symlink_found
        and set(actual) == permitted_paths
        and all(actual.get(path) == digest for path, digest in protected.items())
    )
    return {"scope_ok": valid}


def run_hidden(cases_path: Path, result_path: Path) -> None:
    payload = json.loads(cases_path.read_text())
    spec = importlib.util.spec_from_file_location("_bugfix_submission", LIB_PATH)
    if spec is None or spec.loader is None:
        raise ImportError("could not load /app/repo/lib.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    outputs = []
    for function_name, args in payload["cases"]:
        try:
            function = getattr(module, function_name)
            value = function(*args)
            json.dumps(value, allow_nan=False)
            outputs.append({"ok": True, "value": value})
        except BaseException as error:  # noqa: BLE001
            outputs.append({"ok": False, "error": type(error).__name__})

    result = {"nonce": payload["nonce"], "outputs": outputs}
    encoded = json.dumps(result, allow_nan=False).encode()
    if len(encoded) > MAX_RESULT_BYTES:
        encoded = json.dumps(
            {"nonce": payload["nonce"], "outputs": None, "error": "too_large"}
        ).encode()
    temporary = result_path.with_suffix(".tmp")
    temporary.write_bytes(encoded)
    os.replace(temporary, result_path)


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
