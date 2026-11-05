"""Deterministic generation of small uint32 C programs."""

from __future__ import annotations

import hashlib
import random
from dataclasses import dataclass

MASK = 0xFFFFFFFF
STAGES_PER_LEVEL = {0: 2, 1: 2, 2: 3, 3: 4, 4: 4}


@dataclass(frozen=True)
class Stage:
    kind: str
    operation: str = ""
    value: int = 0


@dataclass(frozen=True)
class DecompileInstance:
    seed: int
    level: int
    files: dict[str, str]
    expected_files: list[str]
    protected_hashes: dict[str, str]
    c_source: str
    reference_source: str
    example_input: list[int]
    example_output: int
    hidden_inputs: list[list[int]]
    raw_constants: list[int]


def _word(rng: random.Random) -> int:
    return rng.getrandbits(32) | 0x10000


def _stage(rng: random.Random) -> Stage:
    kind = rng.choice(("map", "filter", "fold", "prev"))
    if kind == "map":
        operation = rng.choice(("add", "xor", "mul", "rotl"))
        if operation == "rotl":
            value = rng.randint(1, 31)
        elif operation == "mul":
            value = _word(rng) | 1
        else:
            value = _word(rng)
        return Stage(kind, operation, value)
    if kind == "filter":
        operation = rng.choice(("zero_mask", "less_than", "index_mod"))
        value = rng.randint(1, 7) if operation == "index_mod" else _word(rng)
        return Stage(kind, operation, value)
    if kind == "fold":
        operation = rng.choice(("add", "xor", "mul_add"))
        value = _word(rng) if operation == "mul_add" else 0
        return Stage(kind, operation, value)
    return Stage("prev")


def _reference_source(
    initial: int,
    stages: list[Stage],
    final_a: int,
    multiplier: int,
    final_b: int,
) -> str:
    lines = [
        "MASK = 0xFFFFFFFF",
        "",
        "def f(xs: list[int]) -> int:",
        "    xs = list(xs)",
        f"    acc = 0x{initial:08X}",
    ]
    for stage in stages:
        if stage.kind == "map":
            if stage.operation == "add":
                expression = f"(x + 0x{stage.value:08X}) & MASK"
            elif stage.operation == "xor":
                expression = f"x ^ 0x{stage.value:08X}"
            elif stage.operation == "mul":
                expression = f"(x * 0x{stage.value:08X}) & MASK"
            else:
                rotate = stage.value
                expression = f"((x << {rotate}) | (x >> {32 - rotate})) & MASK"
            lines.append(f"    xs = [{expression} for x in xs]")
        elif stage.kind == "filter":
            if stage.operation == "zero_mask":
                condition = f"(x & 0x{stage.value:08X}) == 0"
            elif stage.operation == "less_than":
                condition = f"x < 0x{stage.value:08X}"
            else:
                condition = f"i % {stage.value} == 0"
            lines.extend(
                [
                    "    kept = []",
                    "    for i, x in enumerate(xs):",
                    f"        if not ({condition}):",
                    "            kept.append(x)",
                    "    xs = kept",
                ]
            )
        elif stage.kind == "fold":
            lines.append("    for x in xs:")
            if stage.operation == "add":
                lines.append("        acc = (acc + x) & MASK")
            elif stage.operation == "xor":
                lines.append("        acc ^= x")
            else:
                lines.append(f"        acc = (acc * 0x{stage.value:08X} + x) & MASK")
        else:
            lines.extend(
                [
                    "    previous = 0",
                    "    transformed = []",
                    "    for x in xs:",
                    "        transformed.append(x ^ previous)",
                    "        previous = x",
                    "    xs = transformed",
                ]
            )
    lines.extend(
        [
            f"    acc ^= acc >> {final_a}",
            f"    acc = (acc * 0x{multiplier:08X}) & MASK",
            f"    acc ^= acc >> {final_b}",
            "    return acc & MASK",
            "",
        ]
    )
    return "\n".join(lines)


def _stage_c(stage: Stage, index: int, constant) -> list[str]:
    prefix = f"stage_{index}"
    if stage.kind == "map":
        if stage.operation == "rotl":
            return [
                f"        uint32_t {prefix}_rotate = {constant(stage.value)};",
                "        for (size_t i = 0; i < n; i++) {",
                (
                    f"            xs[i] = (xs[i] << {prefix}_rotate) | "
                    f"(xs[i] >> (32u - {prefix}_rotate));"
                ),
                "        }",
            ]
        symbol = {"add": "+=", "xor": "^=", "mul": "*="}[stage.operation]
        return [
            f"        uint32_t {prefix}_constant = {constant(stage.value)};",
            "        for (size_t i = 0; i < n; i++) {",
            f"            xs[i] {symbol} {prefix}_constant;",
            "        }",
        ]
    if stage.kind == "filter":
        if stage.operation == "index_mod":
            condition = f"i % {prefix}_constant == 0u"
        elif stage.operation == "zero_mask":
            condition = f"(xs[i] & {prefix}_constant) == 0u"
        else:
            condition = f"xs[i] < {prefix}_constant"
        return [
            f"        uint32_t {prefix}_constant = {constant(stage.value)};",
            "        size_t output = 0;",
            "        for (size_t i = 0; i < n; i++) {",
            f"            if (!({condition})) xs[output++] = xs[i];",
            "        }",
            "        n = output;",
        ]
    if stage.kind == "fold":
        lines = []
        if stage.operation == "mul_add":
            lines.append(
                f"        uint32_t {prefix}_constant = {constant(stage.value)};"
            )
        lines.append("        for (size_t i = 0; i < n; i++) {")
        if stage.operation == "add":
            lines.append("            acc += xs[i];")
        elif stage.operation == "xor":
            lines.append("            acc ^= xs[i];")
        else:
            lines.append(f"            acc = acc * {prefix}_constant + xs[i];")
        lines.append("        }")
        return lines
    return [
        "        uint32_t previous = 0;",
        "        for (size_t i = 0; i < n; i++) {",
        "            uint32_t current = xs[i];",
        "            xs[i] = current ^ previous;",
        "            previous = current;",
        "        }",
    ]


def _c_source(
    level: int,
    seed: int,
    initial: int,
    stages: list[Stage],
    final_a: int,
    multiplier: int,
    final_b: int,
    key: int,
) -> str:
    encoded = level == 4
    lines = [
        "#include <errno.h>",
        "#include <inttypes.h>",
        "#include <stdint.h>",
        "#include <stdio.h>",
        "#include <stdlib.h>",
        "",
    ]
    if encoded:
        lines.extend(
            [
                f"static volatile uint32_t decode_key = 0x{key:08X}u;",
                "static int opaque_true(uint32_t value) {",
                '    __asm__ volatile("" : "+r"(value));',
                "    return ((value * value + value) & 1u) == 0u;",
                "}",
                "",
            ]
        )

    def constant(value: int) -> str:
        if encoded:
            return f"(0x{value ^ key:08X}u ^ decode_key)"
        return f"0x{value:08X}u"

    lines.extend(
        [
            "int main(int argc, char **argv) {",
            "    if (argc > 13) return 1;",
            "    size_t n = (size_t)(argc - 1);",
            "    uint32_t xs[12];",
            "    for (size_t i = 0; i < n; i++) {",
            "        char *end = NULL;",
            "        errno = 0;",
            "        unsigned long long value = strtoull(argv[i + 1], &end, 10);",
            "        if (errno != 0 || end == argv[i + 1] || *end != '\\0' ||",
            "            value > UINT32_MAX) return 1;",
            "        xs[i] = (uint32_t)value;",
            "    }",
            f"    uint32_t acc = {constant(initial)};",
        ]
    )

    def final_code(indent: str = "    ") -> list[str]:
        return [
            f"{indent}uint32_t final_a = {constant(final_a)};",
            f"{indent}uint32_t final_b = {constant(final_b)};",
            f"{indent}uint32_t final_multiplier = {constant(multiplier)};",
            f"{indent}acc ^= acc >> final_a;",
            f"{indent}acc *= final_multiplier;",
            f"{indent}acc ^= acc >> final_b;",
            f'{indent}printf("%" PRIu32 "\\n", acc);',
            f"{indent}return 0;",
        ]

    if level < 3:
        for index, stage in enumerate(stages):
            lines.append("    {")
            lines.extend(_stage_c(stage, index, constant))
            lines.append("    }")
        lines.extend(final_code())
    else:
        control_rng = random.Random(seed ^ 0x6A09E667)
        states = control_rng.sample(range(1000, 1_000_000), len(stages) + 1)
        lines.extend(
            [
                f"    volatile uint32_t state = {states[0]}u;",
                "    while (1) {",
                "        switch (state) {",
            ]
        )
        for index, stage in enumerate(stages):
            lines.extend(
                [
                    f"        case {states[index]}u: {{",
                ]
            )
            if encoded:
                lines.extend(
                    [
                        (
                            "            uint32_t opaque_input = acc ^ "
                            "(n == 0 ? 0u : xs[0]);"
                        ),
                        "            if (opaque_true(opaque_input)) {",
                    ]
                )
                lines.extend(
                    line.replace("        ", "                ", 1)
                    for line in _stage_c(stage, index, constant)
                )
                lines.extend(
                    [
                        "            } else {",
                        "                return 1;",
                        "            }",
                        "            if (!opaque_true(opaque_input)) {",
                        "                volatile uint32_t junk = opaque_input + 1u;",
                        "                (void)junk;",
                        "            }",
                    ]
                )
            else:
                lines.extend(_stage_c(stage, index, constant))
            lines.extend(
                [
                    f"            state = {states[index + 1]}u;",
                    "            break;",
                    "        }",
                ]
            )
        lines.extend(
            [
                f"        case {states[-1]}u: {{",
            ]
        )
        if encoded:
            lines.extend(
                [
                    (
                        "            uint32_t opaque_input = acc ^ "
                        "(n == 0 ? 0u : xs[0]);"
                    ),
                    "            if (opaque_true(opaque_input)) {",
                ]
            )
            lines.extend(
                line.replace("    ", "                ", 1)
                for line in final_code(indent="    ")
            )
            lines.extend(
                [
                    "            } else {",
                    "                return 1;",
                    "            }",
                    "            if (!opaque_true(opaque_input)) {",
                    "                volatile uint32_t junk = opaque_input + 1u;",
                    "                (void)junk;",
                    "            }",
                    "            break;",
                    "        }",
                ]
            )
        else:
            lines.extend(final_code(indent="            "))
            lines.append("        }")
        lines.extend(
            [
                "        default:",
                "            return 1;",
                "        }",
                "    }",
            ]
        )
    lines.extend(["}", ""])
    return "\n".join(lines)


def _random_input(rng: random.Random, length: int | None = None) -> list[int]:
    if length is None:
        length = rng.randint(0, 12)
    return [rng.getrandbits(32) for _ in range(length)]


def generate(seed: int, level: int) -> DecompileInstance:
    """Generate a deterministic compiled uint32 program."""
    if level not in STAGES_PER_LEVEL:
        raise ValueError(f"unsupported decompile level: {level}")
    rng = random.Random(seed ^ (level * 0x9E3779B9) ^ 0x243F6A88)
    initial = _word(rng)
    stages = [_stage(rng) for _ in range(STAGES_PER_LEVEL[level])]
    final_a = rng.randint(1, 31)
    multiplier = _word(rng) | 1
    final_b = rng.randint(1, 31)
    key = (rng.getrandbits(32) | 1) if level == 4 else 0
    reference_source = _reference_source(initial, stages, final_a, multiplier, final_b)
    c_source = _c_source(
        level,
        seed,
        initial,
        stages,
        final_a,
        multiplier,
        final_b,
        key,
    )
    input_rng = random.Random(seed ^ (level * 0xBB67AE85) ^ 0x3C6EF372)
    example_input = _random_input(input_rng, input_rng.randint(3, 5))
    hidden_inputs = [[], _random_input(input_rng, 1), [0, MASK]]
    hidden_inputs.append(_random_input(input_rng, 12))
    seen = {tuple(example_input), *(tuple(xs) for xs in hidden_inputs)}
    while len(hidden_inputs) < 50:
        xs = _random_input(input_rng)
        if tuple(xs) not in seen:
            seen.add(tuple(xs))
            hidden_inputs.append(xs)
    namespace: dict[str, object] = {}
    exec(compile(reference_source, "<trusted-decompile-reference>", "exec"), namespace)  # noqa: S102
    function = namespace["f"]
    example_output = function(example_input)
    files = {"prog.c": c_source} if level == 0 else {}
    expected_files = ["prog.c", "prog"] if level == 0 else ["prog"]
    protected_hashes = {
        path: hashlib.sha256(content.encode()).hexdigest()
        for path, content in files.items()
    }
    raw_constants = [initial, multiplier]
    raw_constants.extend(
        stage.value
        for stage in stages
        if stage.kind == "map" and stage.operation in ("add", "xor", "mul")
    )
    raw_constants.extend(
        stage.value
        for stage in stages
        if stage.kind == "filter" and stage.operation in ("zero_mask", "less_than")
    )
    raw_constants.extend(
        stage.value
        for stage in stages
        if stage.kind == "fold" and stage.operation == "mul_add"
    )
    return DecompileInstance(
        seed=seed,
        level=level,
        files=files,
        expected_files=expected_files,
        protected_hashes=protected_hashes,
        c_source=c_source,
        reference_source=reference_source,
        example_input=example_input,
        example_output=example_output,
        hidden_inputs=hidden_inputs,
        raw_constants=raw_constants,
    )
