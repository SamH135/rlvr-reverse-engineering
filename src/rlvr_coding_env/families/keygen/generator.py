"""Deterministic reverse-engineering checker generation."""

from __future__ import annotations

import hashlib
import random
import string
from dataclasses import dataclass

MASK = 0xFFFFFFFF
OPS_PER_LEVEL = {0: 2, 1: 2, 2: 3, 3: 4, 4: 4}
NAME_CHARS = string.ascii_letters + string.digits


@dataclass(frozen=True)
class KeygenOp:
    kind: str
    value: int


@dataclass(frozen=True)
class KeygenInstance:
    seed: int
    level: int
    files: dict[str, str]
    expected_files: list[str]
    protected_hashes: dict[str, str]
    reference_source: str
    check_c_source: str
    example_name: str
    example_serial: str
    hidden_names: list[str]


def _new_name(rng: random.Random) -> str:
    return "".join(rng.choice(NAME_CHARS) for _ in range(rng.randint(3, 16)))


def _parameters(seed: int, level: int):
    rng = random.Random(seed)
    initial = rng.getrandbits(32)
    table = [rng.getrandbits(32) for _ in range(16)]
    operations = []
    for _ in range(OPS_PER_LEVEL[level]):
        kind = rng.choice(("rotl_xor", "mul_add", "table", "shift_add"))
        if kind == "rotl_xor":
            value = rng.randint(1, 31)
        elif kind == "mul_add":
            value = rng.getrandbits(32) | 1
        elif kind == "shift_add":
            value = rng.randint(0, 24)
        else:
            value = 0
        operations.append(KeygenOp(kind, value))
    final_a = rng.randint(1, 31)
    multiplier = rng.getrandbits(32) | 1
    final_b = rng.randint(1, 31)
    key = rng.getrandbits(32) if level == 4 else 0
    return initial, table, operations, final_a, multiplier, final_b, key


def _reference_source(
    initial: int,
    table: list[int],
    operations: list[KeygenOp],
    final_a: int,
    multiplier: int,
    final_b: int,
) -> str:
    lines = [
        f"TABLE = {tuple(table)!r}",
        "",
        "def serial(name: str) -> str:",
        f"    h = 0x{initial:08X}",
        '    for i, c in enumerate(name.encode("ascii")):',
    ]
    for operation in operations:
        if operation.kind == "rotl_xor":
            rotate = operation.value
            lines.extend(
                [
                    f"        h = (((h << {rotate}) | (h >> {32 - rotate})) & 0xFFFFFFFF) ^ c",
                    "        h &= 0xFFFFFFFF",
                ]
            )
        elif operation.kind == "mul_add":
            lines.append(f"        h = (h * 0x{operation.value:08X} + c) & 0xFFFFFFFF")
        elif operation.kind == "table":
            lines.append("        h = (h ^ TABLE[(c + i) & 15]) & 0xFFFFFFFF")
        else:
            lines.append(f"        h = (h + (c << {operation.value})) & 0xFFFFFFFF")
    lines.extend(
        [
            f"    h ^= h >> {final_a}",
            f"    h = (h * 0x{multiplier:08X}) & 0xFFFFFFFF",
            f"    h ^= h >> {final_b}",
            '    return f"{h >> 16:04X}-{h & 0xFFFF:04X}"',
            "",
        ]
    )
    return "\n".join(lines)


def _c_source(
    level: int,
    initial: int,
    table: list[int],
    operations: list[KeygenOp],
    final_a: int,
    multiplier: int,
    final_b: int,
    key: int,
) -> str:
    encoded = level == 4

    def constant(value: int) -> str:
        if encoded:
            value ^= key
        return f"0x{value:08X}u"

    lines = [
        "#include <stdint.h>",
        "#include <stdio.h>",
        "#include <string.h>",
        "",
    ]
    if encoded:
        lines.append(f"static volatile uint32_t decode_key = 0x{key:08X}u;")
    c_table = ", ".join(constant(value) for value in table)
    lines.extend(
        [
            f"static const uint32_t table[16] = {{{c_table}}};",
            "",
            "static int valid_name(const char *name) {",
            "    size_t n = strlen(name);",
            "    if (n < 3 || n > 16) return 0;",
            "    for (size_t i = 0; i < n; i++) {",
            "        unsigned char c = (unsigned char)name[i];",
            "        if (!((c >= 'A' && c <= 'Z') || (c >= 'a' && c <= 'z') ||",
            "              (c >= '0' && c <= '9'))) return 0;",
            "    }",
            "    return 1;",
            "}",
            "",
            "int main(int argc, char **argv) {",
            "    if (argc != 3 || !valid_name(argv[1])) {",
            '        puts("REJECTED");',
            "        return 1;",
            "    }",
        ]
    )
    init_value = f"{constant(initial)} ^ decode_key" if encoded else constant(initial)
    lines.extend(
        [
            f"    uint32_t h = {init_value};",
            "    const char *name = argv[1];",
            "    for (size_t i = 0; name[i] != '\\0'; i++) {",
            "        uint32_t c = (unsigned char)name[i];",
        ]
    )
    for operation in operations:
        if operation.kind == "rotl_xor":
            rotate = operation.value
            lines.extend(
                [
                    f"        h = ((h << {rotate}) | (h >> {32 - rotate})) ^ c;",
                ]
            )
        elif operation.kind == "mul_add":
            suffix = " ^ decode_key" if encoded else ""
            lines.append(f"        h = h * ({constant(operation.value)}{suffix}) + c;")
        elif operation.kind == "table":
            suffix = " ^ decode_key" if encoded else ""
            lines.append(f"        h ^= table[(c + i) & 15]{suffix};")
        else:
            lines.append(f"        h += c << {operation.value};")
    lines.append("    }")
    suffix = " ^ decode_key" if encoded else ""
    lines.extend(
        [
            f"    h ^= h >> {final_a};",
            f"    h *= ({constant(multiplier)}{suffix});",
            f"    h ^= h >> {final_b};",
            "    char expected[10];",
            '    snprintf(expected, sizeof(expected), "%04X-%04X",',
            "             (unsigned)(h >> 16), (unsigned)(h & 0xFFFF));",
            "    int accepted = strcmp(argv[2], expected) == 0;",
            '    puts(accepted ? "ACCEPTED" : "REJECTED");',
            "    return accepted ? 0 : 1;",
            "}",
            "",
        ]
    )
    return "\n".join(lines)


def _python_checker(reference_source: str) -> str:
    return (
        f"{reference_source}"
        "import sys\n\n"
        "def valid_name(name):\n"
        "    return 3 <= len(name) <= 16 and name.isascii() and name.isalnum()\n\n"
        "def main(argv):\n"
        "    if len(argv) != 3 or not valid_name(argv[1]):\n"
        "        print('REJECTED')\n"
        "        return 1\n"
        "    accepted = argv[2] == serial(argv[1])\n"
        "    print('ACCEPTED' if accepted else 'REJECTED')\n"
        "    return 0 if accepted else 1\n\n"
        "if __name__ == '__main__':\n"
        "    raise SystemExit(main(sys.argv))\n"
    )


def generate(seed: int, level: int) -> KeygenInstance:
    """Generate a deterministic key generator checker for one difficulty level."""
    if level not in OPS_PER_LEVEL:
        raise ValueError(f"unsupported keygen level: {level}")
    initial, table, operations, final_a, multiplier, final_b, key = _parameters(
        seed, level
    )
    reference_source = _reference_source(
        initial, table, operations, final_a, multiplier, final_b
    )
    check_c_source = _c_source(
        level,
        initial,
        table,
        operations,
        final_a,
        multiplier,
        final_b,
        key,
    )
    name_rng = random.Random(seed ^ 0xA54FF53A)
    example_name = _new_name(name_rng)
    hidden_names = []
    while len(hidden_names) < 50:
        name = _new_name(name_rng)
        if name != example_name and name not in hidden_names:
            hidden_names.append(name)
    files = (
        {"check.py": _python_checker(reference_source)}
        if level == 0
        else {"check.c": check_c_source}
        if level == 1
        else {}
    )
    expected_files = (
        ["check.py"]
        if level == 0
        else ["check.c", "check"]
        if level == 1
        else ["check"]
    )
    protected_hashes = {
        path: hashlib.sha256(content.encode()).hexdigest()
        for path, content in files.items()
    }
    namespace: dict[str, object] = {}
    exec(compile(reference_source, "<trusted-keygen-reference>", "exec"), namespace)  # noqa: S102
    serial = namespace["serial"]
    return KeygenInstance(
        seed=seed,
        level=level,
        files=files,
        expected_files=expected_files,
        protected_hashes=protected_hashes,
        reference_source=reference_source,
        check_c_source=check_c_source,
        example_name=example_name,
        example_serial=serial(example_name),
        hidden_names=hidden_names,
    )
