import pytest

from rlvr_coding_env.families.bugfix.generator import generate as bugfix_generate
from rlvr_coding_env.families.decompile.generator import (
    generate as decompile_generate,
)
from rlvr_coding_env.families.formats.generator import generate as formats_generate
from rlvr_coding_env.families.keygen.generator import generate as keygen_generate


@pytest.mark.slow
def test_twenty_seeds_per_family_generate():
    for generate, level in [
        (keygen_generate, 0),
        (decompile_generate, 0),
        (formats_generate, 0),
        (bugfix_generate, 1),
    ]:
        for seed in range(20):
            assert generate(seed, level).seed == seed
