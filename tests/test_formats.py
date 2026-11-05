import shutil
import struct
import subprocess

import pytest
import verifiers.v1 as vf

from rlvr_coding_env.families.formats.generator import (
    canonical_json,
    generate,
    generate_test_files,
)
from rlvr_coding_env.families.formats.taskset import FormatsData


def _reference(source: str):
    namespace = {}
    exec(compile(source, "<formats-reference>", "exec"), namespace)  # noqa: S102
    return namespace["parse"]


def _compile(instance, binary):
    source = binary.with_suffix(".c")
    source.write_text(instance.c_source, encoding="utf-8")
    subprocess.run(
        [
            "gcc",
            "-O0" if instance.level <= 1 else "-O2",
            str(source),
            "-o",
            str(binary),
        ],
        check=True,
        capture_output=True,
    )
    if instance.level >= 2:
        subprocess.run(["strip", str(binary)], check=True, capture_output=True)


def test_task_data_json_round_trip_preserves_binary_files():
    instance = generate(0, 0)
    data = FormatsData(
        id="formats-l0-0",
        prompt="",
        seed=instance.seed,
        level=instance.level,
        files=instance.files,
        expected_files=instance.expected_files,
        protected_hashes=instance.protected_hashes,
        c_source=instance.c_source,
        reference_source=instance.reference_source,
        sample_a_hex=instance.sample_a.hex(),
        hidden_files_hex=[item.hex() for item in instance.hidden_files],
        valid_count=instance.valid_count,
        image="rlvr-keygen:0.1",
        workdir="/app/repo",
        network=vf.NetworkPolicyConfig(allow=[]),
        scoring=vf.ScoringConfig(mode="isolated"),
        artifacts=[vf.Artifact(source="/app/repo")],
    )
    encoded = data.model_dump(mode="json")
    decoded = FormatsData.model_validate(encoded)
    assert encoded["files"]["reader.c"] == instance.files["reader.c"].hex()
    assert decoded.files == instance.files


@pytest.mark.parametrize("level", range(5))
def test_generation_is_deterministic_and_hidden_files_match_the_reference(level: int):
    for seed in range(20):
        instance = generate(seed, level)
        assert instance == generate(seed, level)
        assert len(instance.hidden_files) == 50
        assert len(set(instance.hidden_files)) == 50
        assert instance.valid_count == 38
        assert not set(instance.hidden_files) & {
            instance.files["samples/a.bin"],
            instance.files["samples/b.bin"],
        }
        parser = _reference(instance.reference_source)
        assert instance.sample_a_output == canonical_json(parser(instance.sample_a))
        assert all(parser(data) is not None for data in instance.hidden_files[:38])
        assert all(parser(data) is None for data in instance.hidden_files[38:])
        if level == 0:
            assert set(instance.files) == {
                "reader.c",
                "samples/a.bin",
                "samples/b.bin",
            }
            assert instance.expected_files == [
                "reader.c",
                "reader",
                "samples/a.bin",
                "samples/b.bin",
            ]
        else:
            assert set(instance.files) == {"samples/a.bin", "samples/b.bin"}
            assert instance.expected_files == [
                "reader",
                "samples/a.bin",
                "samples/b.bin",
            ]


@pytest.mark.skipif(
    shutil.which("gcc") is None or shutil.which("strip") is None,
    reason="host gcc or strip is unavailable",
)
@pytest.mark.parametrize("level", range(5))
def test_reference_and_compiled_reader_match_on_200_files_per_seed(
    tmp_path, level: int
):
    for seed in range(20):
        instance = generate(seed, level)
        binary = tmp_path / f"reader-{level}-{seed}"
        _compile(instance, binary)
        parser = _reference(instance.reference_source)
        file_path = tmp_path / "input.bin"
        for data in [
            instance.files["samples/a.bin"],
            instance.files["samples/b.bin"],
            *generate_test_files(instance),
        ]:
            file_path.write_bytes(data)
            result = subprocess.run(
                [str(binary), str(file_path)],
                check=False,
                capture_output=True,
                text=True,
            )
            expected = parser(data)
            if expected is None:
                assert result.returncode != 0
                assert result.stdout == "INVALID\n"
            else:
                assert result.returncode == 0
                assert result.stdout == canonical_json(expected) + "\n"


@pytest.mark.skipif(
    shutil.which("gcc") is None or shutil.which("strip") is None,
    reason="host gcc or strip is unavailable",
)
def test_level_four_reader_does_not_contain_raw_format_constants(tmp_path):
    instance = generate(0, 4)
    binary = tmp_path / "reader-4"
    _compile(instance, binary)
    program = binary.read_bytes()
    assert all(
        struct.pack("<I", value) not in program
        and struct.pack(">I", value) not in program
        for value in instance.raw_constants
    )
