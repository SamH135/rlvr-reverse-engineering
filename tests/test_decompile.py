import random
import shutil
import struct
import subprocess

import pytest

from rlvr_coding_env.families.decompile.generator import generate


def _reference(source: str):
    namespace = {}
    exec(compile(source, "<decompile-reference>", "exec"), namespace)  # noqa: S102
    return namespace["f"]


def _compile(instance, binary, optimize: str):
    source = binary.with_suffix(".c")
    source.write_text(instance.c_source, encoding="utf-8")
    subprocess.run(
        ["gcc", optimize, str(source), "-o", str(binary)],
        check=True,
        capture_output=True,
    )
    if instance.level >= 2:
        subprocess.run(["strip", str(binary)], check=True, capture_output=True)


def _run(binary, xs: list[int]) -> int:
    result = subprocess.run(
        [str(binary), *(str(value) for value in xs)],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    return int(result.stdout.strip())


@pytest.mark.parametrize("level", range(5))
def test_generation_is_deterministic_and_has_required_hidden_shapes(level: int):
    for seed in range(20):
        instance = generate(seed, level)
        assert instance == generate(seed, level)
        assert len(instance.hidden_inputs) == 50
        assert len({tuple(xs) for xs in instance.hidden_inputs}) == 50
        assert [] in instance.hidden_inputs
        assert any(len(xs) == 1 for xs in instance.hidden_inputs)
        assert [0, 0xFFFFFFFF] in instance.hidden_inputs
        assert any(len(xs) == 12 for xs in instance.hidden_inputs)
        assert all(
            len(xs) <= 12 and all(0 <= value <= 0xFFFFFFFF for value in xs)
            for xs in [instance.example_input, *instance.hidden_inputs]
        )
        reference = _reference(instance.reference_source)
        assert all(
            type(reference(xs)) is int and 0 <= reference(xs) <= 0xFFFFFFFF
            for xs in instance.hidden_inputs
        )
        if level == 0:
            assert set(instance.files) == {"prog.c"}
            assert instance.expected_files == ["prog.c", "prog"]
        else:
            assert instance.files == {}
            assert instance.expected_files == ["prog"]


@pytest.mark.skipif(shutil.which("gcc") is None, reason="host gcc is unavailable")
@pytest.mark.parametrize("level", range(5))
def test_reference_matches_compiled_program_on_200_inputs_per_seed(
    tmp_path, level: int
):
    for seed in range(20):
        instance = generate(seed, level)
        binary = tmp_path / f"prog-{level}-{seed}"
        optimize = "-O0" if level <= 1 else "-O2"
        _compile(instance, binary, optimize)
        reference = _reference(instance.reference_source)
        rng = random.Random(seed ^ (level * 0x9E3779B9) ^ 0x243F6A88)
        inputs = [instance.hidden_inputs[index] for index in range(4)]
        inputs.extend(
            [
                [rng.getrandbits(32) for _ in range(rng.randint(0, 12))]
                for _ in range(200)
            ]
        )
        for xs in inputs:
            assert _run(binary, xs) == reference(xs)


@pytest.mark.skipif(
    shutil.which("gcc") is None or shutil.which("objdump") is None,
    reason="host gcc or objdump is unavailable",
)
def test_level_three_flattening_increases_disassembly_size(tmp_path):
    counts = []
    for level in (2, 3):
        instance = generate(0, level)
        binary = tmp_path / f"prog-{level}"
        _compile(instance, binary, "-O2")
        disassembly = subprocess.run(
            ["objdump", "-d", str(binary)],
            check=True,
            capture_output=True,
            text=True,
        ).stdout
        counts.append(len(disassembly.splitlines()))
    assert counts[1] > counts[0]


@pytest.mark.skipif(shutil.which("gcc") is None, reason="host gcc is unavailable")
def test_level_four_binary_does_not_contain_raw_data_constants(tmp_path):
    instance = generate(0, 4)
    binary = tmp_path / "prog-4"
    _compile(instance, binary, "-O2")
    program = binary.read_bytes()
    assert all(
        struct.pack("<I", value) not in program
        and struct.pack(">I", value) not in program
        for value in instance.raw_constants
    )
