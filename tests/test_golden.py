import hashlib
import json
import os
from pathlib import Path

import pytest

from rlvr_coding_env.families.bugfix.generator import generate as bugfix_generate
from rlvr_coding_env.families.decompile.generator import (
    generate as decompile_generate,
)
from rlvr_coding_env.families.formats.generator import generate as formats_generate
from rlvr_coding_env.families.keygen.generator import generate as keygen_generate

GOLDEN_PATH = Path(__file__).parent / "golden" / "instances.json"

FIELDS = {
    "keygen": (
        "files",
        "expected_files",
        "protected_hashes",
        "reference_source",
        "check_c_source",
        "example_name",
        "example_serial",
        "hidden_names",
    ),
    "decompile": (
        "files",
        "expected_files",
        "protected_hashes",
        "c_source",
        "reference_source",
        "example_input",
        "example_output",
        "hidden_inputs",
        "raw_constants",
    ),
    "formats": (
        "files",
        "expected_files",
        "protected_hashes",
        "c_source",
        "reference_source",
        "sample_a",
        "sample_a_output",
        "hidden_files",
        "valid_count",
    ),
    "bugfix": (
        "files",
        "protected_hashes",
        "reference_source",
        "hidden_cases",
        "visible_cases",
    ),
}

GENERATORS = {
    "keygen": (keygen_generate, [0, 4, 5, 6]),
    "decompile": (decompile_generate, [0, 4, 5, 6]),
    "formats": (formats_generate, [0, 4]),
    "bugfix": (bugfix_generate, [1, 2]),
}


def _pure_data(instance, fields):
    data = {}
    for field in fields:
        value = getattr(instance, field)
        if isinstance(value, dict):
            value = {
                key: item.hex() if isinstance(item, bytes) else item
                for key, item in value.items()
            }
        elif isinstance(value, (bytes, bytearray)):
            value = value.hex()
        elif isinstance(value, list):
            value = [
                item.hex() if isinstance(item, bytes) else item for item in value
            ]
        data[field] = value
    return data


def _digest(family: str, level: int) -> str:
    generate, _levels = GENERATORS[family]
    instance = generate(0, level)
    canonical = json.dumps(
        _pure_data(instance, FIELDS[family]), sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(canonical.encode()).hexdigest()


def _expected_digests() -> dict[str, str]:
    return {
        f"{family}-l{level}": _digest(family, level)
        for family, (_generate, levels) in GENERATORS.items()
        for level in levels
    }


def test_golden_instances():
    if os.environ.get("RLVR_UPDATE_GOLDEN") == "1":
        GOLDEN_PATH.parent.mkdir(parents=True, exist_ok=True)
        GOLDEN_PATH.write_text(
            json.dumps(_expected_digests(), indent=2, sort_keys=True) + "\n"
        )
        pytest.skip("regenerated golden digests")
    golden = json.loads(GOLDEN_PATH.read_text())
    actual = _expected_digests()
    assert actual == golden, (
        "generated instances changed; if intentional, regenerate with "
        "RLVR_UPDATE_GOLDEN=1 uv run pytest tests/test_golden.py"
    )
