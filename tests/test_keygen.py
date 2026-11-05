import random
import re
import shutil
import string
import subprocess
import sys

import pytest

from rlvr_coding_env.families.keygen.generator import generate

NAME_CHARS = string.ascii_letters + string.digits


def _namespace(source: str) -> dict[str, object]:
    namespace: dict[str, object] = {}
    exec(compile(source, "<keygen-reference>", "exec"), namespace)  # noqa: S102
    return namespace


def _random_name(rng: random.Random) -> str:
    return "".join(rng.choice(NAME_CHARS) for _ in range(rng.randint(3, 16)))


@pytest.mark.parametrize("level", range(5))
def test_generation_is_deterministic_and_has_distinct_names(level: int):
    for seed in range(100):
        instance = generate(seed, level)
        assert instance == generate(seed, level)
        assert instance.level == level
        assert len(instance.hidden_names) == 50
        assert instance.example_name not in instance.hidden_names
        assert len(set(instance.hidden_names)) == 50
        assert all(
            3 <= len(name) <= 16 and name.isascii() and name.isalnum()
            for name in [instance.example_name, *instance.hidden_names]
        )
        if level == 0:
            assert set(instance.files) == {"check.py"}
            assert instance.expected_files == ["check.py"]
            assert set(instance.protected_hashes) == {"check.py"}
        elif level == 1:
            assert set(instance.files) == {"check.c"}
            assert instance.files["check.c"] == instance.check_c_source
            assert instance.expected_files == ["check.c", "check"]
            assert set(instance.protected_hashes) == {"check.c"}
        else:
            assert instance.files == {}
            assert instance.expected_files == ["check"]
            assert instance.protected_hashes == {}


@pytest.mark.skipif(shutil.which("gcc") is None, reason="host gcc is unavailable")
@pytest.mark.parametrize("level", range(5))
def test_reference_matches_compiled_checker_and_level_zero_python(tmp_path, level: int):
    for seed in range(20):
        instance = generate(seed, level)
        binary = tmp_path / f"check-{seed}"
        subprocess.run(
            ["gcc", "-O0", "-x", "c", "-", "-o", str(binary)],
            input=instance.check_c_source,
            text=True,
            check=True,
            capture_output=True,
        )
        namespace = _namespace(instance.reference_source)
        serial = namespace["serial"]
        rng = random.Random(seed ^ level ^ 0x510E527F)
        check_py = None
        if level == 0:
            check_py = tmp_path / f"check-{seed}.py"
            check_py.write_text(instance.files["check.py"], encoding="utf-8")
        for _ in range(20):
            name = _random_name(rng)
            expected = serial(name)
            result = subprocess.run(
                [str(binary), name, expected],
                capture_output=True,
                check=False,
                text=True,
            )
            assert result.stdout.strip() == "ACCEPTED"
            assert result.returncode == 0
            if check_py is not None:
                python_result = subprocess.run(
                    [sys.executable, str(check_py), name, expected],
                    capture_output=True,
                    check=False,
                    text=True,
                )
                assert python_result.stdout.strip() == "ACCEPTED"
                assert python_result.returncode == 0

        wrong = ("0" if expected[0] != "0" else "1") + expected[1:]
        rejected = subprocess.run(
            [str(binary), name, wrong],
            capture_output=True,
            check=False,
            text=True,
        )
        assert rejected.stdout.strip() == "REJECTED"
        assert rejected.returncode == 1
        usage = subprocess.run(
            [str(binary)], capture_output=True, check=False, text=True
        )
        assert usage.stdout.strip() == "REJECTED"
        assert usage.returncode == 1


@pytest.mark.skipif(
    shutil.which("gcc") is None or shutil.which("strings") is None,
    reason="host gcc or strings is unavailable",
)
def test_level_four_binary_does_not_expose_raw_constants(tmp_path):
    instance = generate(0, 4)
    binary = tmp_path / "check"
    subprocess.run(
        ["gcc", "-O2", "-x", "c", "-", "-o", str(binary)],
        input=instance.check_c_source,
        text=True,
        check=True,
        capture_output=True,
    )
    strings = subprocess.run(
        ["strings", str(binary)], capture_output=True, text=True, check=True
    ).stdout
    raw_constants = set(re.findall(r"0x[0-9A-F]{8}", instance.reference_source))
    assert all(value not in strings for value in raw_constants)
