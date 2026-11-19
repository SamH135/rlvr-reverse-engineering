"""Deterministic generation of small uint32 C programs."""

from __future__ import annotations

import hashlib
import random
from dataclasses import dataclass

MASK = 0xFFFFFFFF
STAGES_PER_LEVEL = {0: 2, 1: 2, 2: 3, 3: 4, 4: 4, 5: 8, 6: 6, 7: 8, 8: 6}
CRYPTO_HELPERS_PY = '''MASK = 0xFFFFFFFF


def xtea32(v, delta, k, rounds):
    s = 0
    for _ in range(rounds):
        s = (s + delta) & MASK
        t = ((((v << 4) & MASK) ^ (v >> 5)) + v) & MASK
        v = (v + (t ^ ((s + k[s & 3]) & MASK))) & MASK
    return v


def crc_table(poly):
    table = []
    for i in range(256):
        c = i
        for _ in range(8):
            c = (c >> 1) ^ (poly if c & 1 else 0)
        table.append(c)
    return table


def crc_update(acc, data, table):
    for b in data:
        acc = table[(acc ^ b) & 0xFF] ^ (acc >> 8)
    return acc


def rc4_keystream(key, n):
    s = list(range(256))
    j = 0
    for i in range(256):
        j = (j + s[i] + key[i % len(key)]) & 0xFF
        s[i], s[j] = s[j], s[i]
    out = bytearray()
    i = j = 0
    for _ in range(n):
        i = (i + 1) & 0xFF
        j = (j + s[i]) & 0xFF
        s[i], s[j] = s[j], s[i]
        out.append(s[(s[i] + s[j]) & 0xFF])
    return bytes(out)


'''
DECOY_TAGS = (
    "crc32 table init",
    "feistel round keys",
    "rc4 ksa done",
    "xtea block decrypt",
    "checksum mismatch",
    "license ok",
)


@dataclass(frozen=True)
class Stage:
    kind: str
    operation: str = ""
    value: int = 0
    params: tuple[int, ...] = ()


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


def c_constant_expression(value: int, key: int | None = None) -> str:
    if key is not None:
        return f"(0x{value ^ key:08X}u ^ decode_key)"
    return f"0x{value:08X}u"


def _indent(lines: list[str], prefix: str) -> list[str]:
    return [f"{prefix}{line}" if line else "" for line in lines]


def emit_c_dispatcher(
    seed: int,
    blocks: list[list[str]],
    final_block: list[str],
    *,
    opaque: bool = False,
    opaque_expression: str = "0u",
) -> list[str]:
    states = random.Random(seed ^ 0x6A09E667).sample(
        range(1000, 1_000_000), len(blocks) + 1
    )
    lines = [
        f"    volatile uint32_t state = {states[0]}u;",
        "    while (1) {",
        "        switch (state) {",
    ]
    for index, block in enumerate(blocks):
        lines.append(f"        case {states[index]}u: {{")
        if opaque:
            lines.extend(
                [
                    f"            uint32_t opaque_input = {opaque_expression};",
                    "            if (opaque_true(opaque_input)) {",
                ]
            )
            lines.extend(_indent(block, "                "))
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
            lines.extend(_indent(block, "            "))
        lines.extend(
            [
                f"            state = {states[index + 1]}u;",
                "            break;",
                "        }",
            ]
        )
    lines.append(f"        case {states[-1]}u: {{")
    if opaque:
        lines.extend(
            [
                f"            uint32_t opaque_input = {opaque_expression};",
                "            if (opaque_true(opaque_input)) {",
            ]
        )
        lines.extend(_indent(final_block, "                "))
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
        lines.extend(_indent(final_block, "            "))
        lines.append("        }")
    lines.extend(
        [
            "        default:",
            "            return 1;",
            "        }",
            "    }",
        ]
    )
    return lines


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


def _make_stages(rng: random.Random, level: int) -> list[Stage]:
    if level != 8:
        return [_stage(rng) for _ in range(STAGES_PER_LEVEL[level])]
    stages = [_stage(rng) for _ in range(3)]
    xtea = Stage(
        "xtea",
        params=(
            _word(rng) | 1,
            _word(rng),
            _word(rng),
            _word(rng),
            _word(rng),
            rng.randint(4, 8),
        ),
    )
    crc = Stage("crc", params=(_word(rng) | 1,))
    rc4 = Stage("rc4", params=tuple(rng.getrandbits(32) for _ in range(4)))
    stages.extend((xtea, crc, rc4))
    rng.shuffle(stages)
    return stages


def _reference_source(
    initial: int,
    stages: list[Stage],
    final_a: int,
    multiplier: int,
    final_b: int,
    level: int,
) -> str:
    lines = [
        "MASK = 0xFFFFFFFF",
        "",
        "def f(xs: list[int]) -> int:",
        "    xs = list(xs)",
        f"    acc = 0x{initial:08X}",
    ]
    for index, stage in enumerate(stages):
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
        elif stage.kind == "xtea":
            delta, k0, k1, k2, k3, rounds = stage.params
            lines.append(
                f"    xs = [xtea32(x, 0x{delta:08X}, "
                f"(0x{k0:08X}, 0x{k1:08X}, 0x{k2:08X}, 0x{k3:08X}), "
                f"{rounds}) for x in xs]"
            )
        elif stage.kind == "crc":
            lines.append(f"    table_{index} = crc_table(0x{stage.params[0]:08X})")
            lines.append("    for x in xs:")
            lines.append(
                "        acc = crc_update(acc, x.to_bytes(4, 'little'), "
                f"table_{index})"
            )
        elif stage.kind == "rc4":
            words = ", ".join(f"0x{w:08X}" for w in stage.params)
            lines.append(
                f"    key_{index} = b''.join(w.to_bytes(4, 'little') "
                f"for w in ({words},))"
            )
            lines.append(
                f"    ks_{index} = rc4_keystream(key_{index}, 4 * len(xs))"
            )
            lines.append(
                f"    xs = [x ^ int.from_bytes(ks_{index}[4 * i:4 * i + 4], "
                "'little') for i, x in enumerate(xs)]"
            )
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
    source = "\n".join(lines)
    if level == 8:
        source = CRYPTO_HELPERS_PY + source
    return source


def _stage_c(stage: Stage, index: int, constant) -> list[str]:
    prefix = f"stage_{index}"
    if stage.kind == "map":
        if stage.operation == "rotl":
            return [
                f"uint32_t {prefix}_rotate = {constant(stage.value)};",
                "for (size_t i = 0; i < n; i++) {",
                (
                    f"    xs[i] = (xs[i] << {prefix}_rotate) | "
                    f"(xs[i] >> (32u - {prefix}_rotate));"
                ),
                "}",
            ]
        symbol = {"add": "+=", "xor": "^=", "mul": "*="}[stage.operation]
        return [
            f"uint32_t {prefix}_constant = {constant(stage.value)};",
            "for (size_t i = 0; i < n; i++) {",
            f"    xs[i] {symbol} {prefix}_constant;",
            "}",
        ]
    if stage.kind == "filter":
        if stage.operation == "index_mod":
            condition = f"i % {prefix}_constant == 0u"
        elif stage.operation == "zero_mask":
            condition = f"(xs[i] & {prefix}_constant) == 0u"
        else:
            condition = f"xs[i] < {prefix}_constant"
        return [
            f"uint32_t {prefix}_constant = {constant(stage.value)};",
            "size_t output = 0;",
            "for (size_t i = 0; i < n; i++) {",
            f"    if (!({condition})) xs[output++] = xs[i];",
            "}",
            "n = output;",
        ]
    if stage.kind == "xtea":
        delta, k0, k1, k2, k3, rounds = stage.params
        return [
            f"uint32_t {prefix}_delta = {constant(delta)};",
            (
                f"uint32_t {prefix}_k[4] = {{{constant(k0)}, {constant(k1)}, "
                f"{constant(k2)}, {constant(k3)}}};"
            ),
            f"uint32_t {prefix}_rounds = {constant(rounds)};",
            "for (size_t i = 0; i < n; i++) {",
            "    uint32_t v = xs[i];",
            "    uint32_t s = 0;",
            f"    for (uint32_t r = 0; r < {prefix}_rounds; r++) {{",
            f"        s += {prefix}_delta;",
            (
                f"        v += ((((v << 4) ^ (v >> 5)) + v) ^ "
                f"(s + {prefix}_k[s & 3]));"
            ),
            "    }",
            "    xs[i] = v;",
            "}",
        ]
    if stage.kind == "crc":
        return [
            f"uint32_t {prefix}_poly = {constant(stage.params[0])};",
            f"uint32_t {prefix}_table[256];",
            "for (int i = 0; i < 256; i++) {",
            "    uint32_t c = (uint32_t)i;",
            "    for (int j = 0; j < 8; j++) {",
            f"        c = (c >> 1) ^ ((c & 1u) ? {prefix}_poly : 0u);",
            "    }",
            f"    {prefix}_table[i] = c;",
            "}",
            "for (size_t i = 0; i < n; i++) {",
            "    uint32_t x = xs[i];",
            "    for (int b = 0; b < 4; b++) {",
            (
                f"        acc = {prefix}_table[(acc ^ (x & 0xFFu)) & 0xFFu] "
                "^ (acc >> 8);"
            ),
            "        x >>= 8;",
            "    }",
            "}",
        ]
    if stage.kind == "rc4":
        words = ", ".join(constant(w) for w in stage.params)
        return [
            f"uint32_t {prefix}_key[4] = {{{words}}};",
            f"uint8_t {prefix}_s[256];",
            "for (int i = 0; i < 256; i++) {",
            f"    {prefix}_s[i] = (uint8_t)i;",
            "}",
            "uint32_t j = 0;",
            "for (int i = 0; i < 256; i++) {",
            (
                f"    j = (j + {prefix}_s[i] + "
                f"(({prefix}_key[(i >> 2) & 3] >> ((i & 3) * 8)) & 0xFFu)) "
                "& 0xFFu;"
            ),
            f"    uint8_t t = {prefix}_s[i];",
            f"    {prefix}_s[i] = {prefix}_s[j];",
            f"    {prefix}_s[j] = t;",
            "}",
            "uint32_t i = 0;",
            "j = 0;",
            "for (size_t e = 0; e < n; e++) {",
            "    uint32_t ks = 0;",
            "    for (int b = 0; b < 4; b++) {",
            "        i = (i + 1) & 0xFFu;",
            f"        j = (j + {prefix}_s[i]) & 0xFFu;",
            f"        uint8_t t = {prefix}_s[i];",
            f"        {prefix}_s[i] = {prefix}_s[j];",
            f"        {prefix}_s[j] = t;",
            (
                f"        ks |= ((uint32_t){prefix}_s[({prefix}_s[i] + "
                f"{prefix}_s[j]) & 0xFFu]) << (8 * b);"
            ),
            "    }",
            "    xs[e] ^= ks;",
            "}",
        ]
    if stage.kind == "fold":
        lines = []
        if stage.operation == "mul_add":
            lines.append(f"uint32_t {prefix}_constant = {constant(stage.value)};")
        lines.append("for (size_t i = 0; i < n; i++) {")
        if stage.operation == "add":
            lines.append("    acc += xs[i];")
        elif stage.operation == "xor":
            lines.append("    acc ^= xs[i];")
        else:
            lines.append(f"    acc = acc * {prefix}_constant + xs[i];")
        lines.append("}")
        return lines
    return [
        "uint32_t previous = 0;",
        "for (size_t i = 0; i < n; i++) {",
        "    uint32_t current = xs[i];",
        "    xs[i] = current ^ previous;",
        "    previous = current;",
        "}",
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
    encoded = level >= 4
    emit_level = 5 if level in (7, 8) else level
    decoys: list[Stage] = []
    decoy_positions: set[int] = set()
    decoy_tags: list[str] = []
    if level == 7:
        # Separate stream so the real program stays identical to L5 per seed.
        decoy_rng = random.Random(seed ^ 0x1F83D9AB)
        decoys = [_stage(decoy_rng) for _ in range(4)]
        decoy_positions = set(decoy_rng.sample(range(12), 4))
        decoy_tags = decoy_rng.sample(DECOY_TAGS, 3)
    lines = [
        "#include <errno.h>",
        "#include <inttypes.h>",
        "#include <stdint.h>",
        "#include <stdio.h>",
        "#include <stdlib.h>",
        "",
    ]
    if encoded:
        lines.append(f"static volatile uint32_t decode_key = 0x{key:08X}u;")
    if emit_level in (4, 5):
        lines.extend(
            [
                "static int opaque_true(uint32_t value) {",
                '    __asm__ volatile("" : "+r"(value));',
                "    return ((value * value + value) & 1u) == 0u;",
                "}",
                "",
            ]
        )

    def constant(value: int) -> str:
        return c_constant_expression(value, key if encoded else None)

    if emit_level == 5:
        for index, stage in enumerate(stages):
            body = [
                line.replace("acc", "(*acc)")
                for line in _stage_c(stage, index, constant)
            ]
            lines.append(
                "static __attribute__((noinline)) void "
                f"stage_{index}(uint32_t *xs, size_t *np, uint32_t *acc) {{"
            )
            lines.append("    size_t n = *np;")
            if stage.kind != "fold":
                lines.append("    (void)acc;")
            lines.extend(_indent(body, "    "))
            lines.extend(["    *np = n;", "}", ""])
        entry_names = [f"stage_{i}" for i in range(len(stages))]
        if level == 7:
            lines.extend(
                [
                    "static volatile uint32_t sink;",
                    "static const char *volatile tag;",
                    "",
                ]
            )
            for decoy_index, decoy in enumerate(decoys):
                lines.append(
                    "static __attribute__((noinline)) void "
                    f"decoy_{decoy_index}(uint32_t *real_xs, size_t *np, "
                    "uint32_t *real_acc) {"
                )
                lines.extend(
                    [
                        "    size_t n = *np;",
                        "    uint32_t acc = *real_acc;",
                        "    uint32_t xs[12];",
                        "    for (size_t i = 0; i < n; i++) {",
                        "        xs[i] = real_xs[i];",
                        "    }",
                    ]
                )
                lines.extend(
                    _indent(_stage_c(decoy, 100 + decoy_index, constant), "    ")
                )
                lines.extend(["    sink = acc ^ (n ? xs[0] : 0u);", "}", ""])
            entry_names = []
            real_index = 0
            decoy_index = 0
            for position in range(12):
                if position in decoy_positions:
                    entry_names.append(f"decoy_{decoy_index}")
                    decoy_index += 1
                else:
                    entry_names.append(f"stage_{real_index}")
                    real_index += 1
        names = ", ".join(entry_names)
        lines.extend(
            [
                (
                    "static void (*const stages[])(uint32_t *, size_t *,"
                    f" uint32_t *) = {{{names}}};"
                ),
                "",
            ]
        )

    vm_body: list[str] = []
    if level == 6:
        code_decl, vm_body = _vm_body(
            seed, stages, final_a, multiplier, final_b, key
        )
        lines.extend(code_decl)

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
    if level == 7:
        lines.extend(f'    tag = "{text}";' for text in decoy_tags)

    def final_code() -> list[str]:
        return [
            f"uint32_t final_a = {constant(final_a)};",
            f"uint32_t final_b = {constant(final_b)};",
            f"uint32_t final_multiplier = {constant(multiplier)};",
            "acc ^= acc >> final_a;",
            "acc *= final_multiplier;",
            "acc ^= acc >> final_b;",
            'printf("%" PRIu32 "\\n", acc);',
            "return 0;",
        ]

    if level < 3:
        for index, stage in enumerate(stages):
            lines.append("    {")
            lines.extend(_indent(_stage_c(stage, index, constant), "        "))
            lines.append("    }")
        lines.extend(_indent(final_code(), "    "))
    elif level == 6:
        lines.extend(vm_body)
    else:
        if emit_level == 5:
            blocks = [
                [
                    f"for (size_t k = 0; k < {len(entry_names)}u; k++) {{",
                    "    stages[k](xs, &n, &acc);",
                    "}",
                ]
            ]
        else:
            blocks = [
                _stage_c(stage, index, constant)
                for index, stage in enumerate(stages)
            ]
        lines.extend(
            emit_c_dispatcher(
                seed,
                blocks,
                final_code(),
                opaque=encoded,
                opaque_expression="acc ^ (n == 0 ? 0u : xs[0])",
            )
        )
    lines.extend(["}", ""])
    return "\n".join(lines)


VM_OPS = (
    "map_add",
    "map_xor",
    "map_mul",
    "map_rotl",
    "filter_zero_mask",
    "filter_less_than",
    "filter_index_mod",
    "fold_add",
    "fold_xor",
    "fold_mul_add",
    "prev",
    "fm_shrx",
    "fm_mul",
)


def _vm_body(
    seed: int,
    stages: list[Stage],
    final_a: int,
    multiplier: int,
    final_b: int,
    key: int,
) -> tuple[list[str], list[str]]:
    """L6: stages compiled to (opcode, XOR-encoded immediate) bytecode."""
    vm_rng = random.Random(seed ^ 0x3C6EF372)
    opcodes = dict(zip(VM_OPS, vm_rng.sample(range(1, 1024), len(VM_OPS))))

    def op_name(stage: Stage) -> str:
        return "prev" if stage.kind == "prev" else f"{stage.kind}_{stage.operation}"

    def immediate(stage: Stage) -> int:
        if stage.kind in ("fold", "prev") and stage.operation != "mul_add":
            return vm_rng.getrandbits(32)  # unused immediate: decoy
        return stage.value

    words = []
    for stage in stages:
        words.append(f"{opcodes[op_name(stage)]}u")
        words.append(f"0x{immediate(stage) ^ key:08X}u")
    for name, value in (
        ("fm_shrx", final_a),
        ("fm_mul", multiplier),
        ("fm_shrx", final_b),
    ):
        words.append(f"{opcodes[name]}u")
        words.append(f"0x{value ^ key:08X}u")

    handlers = {
        "map_add": ["for (size_t i = 0; i < n; i++) xs[i] += imm;"],
        "map_xor": ["for (size_t i = 0; i < n; i++) xs[i] ^= imm;"],
        "map_mul": ["for (size_t i = 0; i < n; i++) xs[i] *= imm;"],
        "map_rotl": [
            "for (size_t i = 0; i < n; i++)",
            "    xs[i] = (xs[i] << imm) | (xs[i] >> (32u - imm));",
        ],
        "filter_zero_mask": [
            "size_t output = 0;",
            "for (size_t i = 0; i < n; i++)",
            "    if (!((xs[i] & imm) == 0u)) xs[output++] = xs[i];",
            "n = output;",
        ],
        "filter_less_than": [
            "size_t output = 0;",
            "for (size_t i = 0; i < n; i++)",
            "    if (!(xs[i] < imm)) xs[output++] = xs[i];",
            "n = output;",
        ],
        "filter_index_mod": [
            "size_t output = 0;",
            "for (size_t i = 0; i < n; i++)",
            "    if (!(i % imm == 0u)) xs[output++] = xs[i];",
            "n = output;",
        ],
        "fold_add": ["for (size_t i = 0; i < n; i++) acc += xs[i];"],
        "fold_xor": ["for (size_t i = 0; i < n; i++) acc ^= xs[i];"],
        "fold_mul_add": [
            "for (size_t i = 0; i < n; i++) acc = acc * imm + xs[i];"
        ],
        "prev": [
            "uint32_t previous = 0;",
            "for (size_t i = 0; i < n; i++) {",
            "    uint32_t current = xs[i];",
            "    xs[i] = current ^ previous;",
            "    previous = current;",
            "}",
        ],
        "fm_shrx": ["acc ^= acc >> imm;"],
        "fm_mul": ["acc *= imm;"],
    }
    lines = ["    for (size_t pc = 0; pc < sizeof(code) / sizeof(code[0]); pc += 2) {",
             "        uint32_t imm = code[pc + 1] ^ decode_key;",
             "        switch (code[pc]) {"]
    used_ops = {op_name(stage) for stage in stages} | {"fm_shrx", "fm_mul"}
    for name in VM_OPS:
        if name not in used_ops:
            continue
        lines.append(f"        case {opcodes[name]}u: {{")
        lines.extend(_indent(handlers[name], "            "))
        lines.extend(["            break;", "        }"])
    lines.extend(
        [
            "        default:",
            "            return 1;",
            "        }",
            "    }",
            '    printf("%" PRIu32 "\\n", acc);',
            "    return 0;",
        ]
    )
    return [
        f"static const uint32_t code[] = {{{', '.join(words)}}};",
        "",
    ], lines


def _random_input(rng: random.Random, length: int | None = None) -> list[int]:
    if length is None:
        length = rng.randint(0, 12)
    return [rng.getrandbits(32) for _ in range(length)]


def generate(seed: int, level: int) -> DecompileInstance:
    """Generate a deterministic compiled uint32 program."""
    if level not in STAGES_PER_LEVEL:
        raise ValueError(f"unsupported decompile level: {level}")
    # L7 reuses the L5 real program so decoys are the only difference per seed.
    rng_level = 5 if level == 7 else level
    rng = random.Random(seed ^ (rng_level * 0x9E3779B9) ^ 0x243F6A88)
    initial = _word(rng)
    stages = _make_stages(rng, rng_level)
    final_a = rng.randint(1, 31)
    multiplier = _word(rng) | 1
    final_b = rng.randint(1, 31)
    key = (rng.getrandbits(32) | 1) if rng_level >= 4 else 0
    input_rng = random.Random(seed ^ (rng_level * 0xBB67AE85) ^ 0x3C6EF372)
    example_input = _random_input(input_rng, input_rng.randint(3, 5))
    hidden_inputs = [[], _random_input(input_rng, 1), [0, MASK]]
    hidden_inputs.append(_random_input(input_rng, 12))
    seen = {tuple(example_input), *(tuple(xs) for xs in hidden_inputs)}
    while len(hidden_inputs) < 50:
        xs = _random_input(input_rng)
        if tuple(xs) not in seen:
            seen.add(tuple(xs))
            hidden_inputs.append(xs)
    for _ in range(64):
        # Only "fold" stages mix xs into acc; re-roll constant programs.
        reference_source = _reference_source(
            initial, stages, final_a, multiplier, final_b, rng_level
        )
        namespace: dict[str, object] = {}
        exec(  # noqa: S102
            compile(reference_source, "<trusted-decompile-reference>", "exec"),
            namespace,
        )
        function = namespace["f"]
        if len({function(xs) for xs in hidden_inputs}) > 1:
            break
        stages = _make_stages(rng, rng_level)
    else:
        raise RuntimeError(f"could not generate an input-dependent program (seed {seed})")
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
    for stage in stages:
        if stage.kind == "xtea":
            raw_constants.extend(stage.params[:5])  # delta + key, not rounds
        elif stage.kind == "crc":
            raw_constants.append(stage.params[0])
        elif stage.kind == "rc4":
            raw_constants.extend(stage.params)
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
