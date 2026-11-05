"""Seeded binary-format instances and their C/Python readers."""

from __future__ import annotations

import hashlib
import json
import random
import string
from dataclasses import dataclass

from rlvr_coding_env.families.decompile.generator import (
    c_constant_expression,
    emit_c_dispatcher,
)

MASK = 0xFFFFFFFF
FIELD_NAMES = (
    "id",
    "qty",
    "price_cents",
    "timestamp",
    "flags",
    "sku",
    "name",
    "region",
    "code",
    "count",
    "amount",
    "status",
    "category",
    "checksum",
    "length",
    "score",
    "sequence",
    "version",
    "zone",
    "enabled",
    "label",
    "owner",
    "rating",
    "stock",
    "account_id",
    "temperature",
    "priority",
    "created_at",
    "source",
    "item_count",
    "balance",
)
STRING_ALPHABET = string.ascii_letters + string.digits + " -_"


@dataclass(frozen=True)
class Field:
    name: str
    kind: str
    endian: str = "little"
    optional: bool = False


@dataclass(frozen=True)
class FormatsInstance:
    seed: int
    level: int
    files: dict[str, bytes]
    expected_files: list[str]
    protected_hashes: dict[str, str]
    c_source: str
    reference_source: str
    sample_a: bytes
    sample_a_output: str
    hidden_files: list[bytes]
    valid_count: int
    raw_constants: list[int]
    format_spec: dict[str, object]


def canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _field_to_dict(field: Field) -> dict[str, object]:
    return {
        "name": field.name,
        "kind": field.kind,
        "endian": field.endian,
        "optional": field.optional,
    }


def _int_width(kind: str) -> int:
    return {"u8": 1, "u16": 2, "u32": 4}[kind]


def _checksum(data: bytes, kind: str, modulus: int) -> int:
    if kind == "sum32":
        return sum(data) & MASK
    if kind == "xor32":
        result = 0
        for offset in range(0, len(data), 4):
            word = int.from_bytes(data[offset : offset + 4].ljust(4, b"\0"), "little")
            result ^= word
        return result
    first = 1
    second = 0
    for byte in data:
        first = (first + byte) % modulus
        second = (second + first) % modulus
    return (second << 16) | first


def _reference_source(spec: dict[str, object]) -> str:
    return f"""SPEC = {spec!r}
MASK = 0xFFFFFFFF

def _checksum(data):
    kind = SPEC["checksum_kind"]
    if kind == "sum32":
        return sum(data) & MASK
    if kind == "xor32":
        result = 0
        for offset in range(0, len(data), 4):
            word = int.from_bytes(data[offset:offset + 4].ljust(4, b"\\0"), "little")
            result ^= word
        return result
    first = 1
    second = 0
    modulus = SPEC["checksum_modulus"]
    for byte in data:
        first = (first + byte) % modulus
        second = (second + first) % modulus
    return (second << 16) | first

def _read(data, offset, end, field):
    kind = field["kind"]
    if kind == "str":
        if offset >= end:
            raise ValueError
        length = data[offset]
        offset += 1
        next_offset = offset + length
        if next_offset > end:
            raise ValueError
        raw = data[offset:next_offset]
        if any(byte < 32 or byte > 126 for byte in raw):
            raise ValueError
        return raw.decode("ascii"), next_offset
    if kind == "varint":
        value = 0
        shift = 0
        for index in range(5):
            if offset >= end:
                raise ValueError
            byte = data[offset]
            offset += 1
            if index == 4 and byte & 0xF0:
                raise ValueError
            value |= (byte & 0x7F) << shift
            if not byte & 0x80:
                if index and not byte & 0x7F:
                    raise ValueError
                return value, offset
            shift += 7
        raise ValueError
    width = {{"u8": 1, "u16": 2, "u32": 4}}[kind]
    next_offset = offset + width
    if next_offset > end:
        raise ValueError
    return int.from_bytes(data[offset:next_offset], field["endian"]), next_offset

def parse(data: bytes):
    try:
        data = bytes(data)
        level = SPEC["level"]
        end = len(data) - (4 if level >= 2 else 0)
        if end < 5 + SPEC["count_width"]:
            return None
        if data[:4] != SPEC["magic"] or data[4] != SPEC["version"]:
            return None
        if level >= 2:
            stored = int.from_bytes(data[end:], "little")
            if _checksum(data[:end]) != stored:
                return None
        offset = 5
        next_offset = offset + SPEC["count_width"]
        if next_offset > end:
            return None
        count = int.from_bytes(data[offset:next_offset], SPEC["count_endian"])
        offset = next_offset
        if count > 8:
            return None
        header = {{}}
        for field in SPEC["header_fields"]:
            value, offset = _read(data, offset, end, field)
            header[field["name"]] = value
        record_start = offset
        if level == 4:
            decoded = bytearray(data)
            key = SPEC["rolling_key"]
            for index in range(record_start, end):
                decoded[index] ^= key & 0xFF
                key = (key * SPEC["rolling_a"] + SPEC["rolling_c"]) & MASK
            data = bytes(decoded)
        records = []
        flag_is_set = True
        if level >= 3:
            flag_is_set = bool(header["flags"] & SPEC["optional_mask"])
        for _ in range(count):
            record = {{}}
            for field in SPEC["record_fields"]:
                if field["optional"] and not flag_is_set:
                    continue
                value, offset = _read(data, offset, end, field)
                record[field["name"]] = value
            records.append(record)
        if offset != end:
            return None
        return {{"header": header, "records": records}}
    except (IndexError, OverflowError, TypeError, ValueError):
        return None
"""


def _c_read_field(field: Field, target: str, *, constant) -> list[str]:
    if field.kind == "str":
        return [
            f"if (!read_string(data, payload_end, &offset, &{target})) return invalid();"
        ]
    if field.kind == "varint":
        return [
            f"if (!read_varint(data, payload_end, &offset, &{target}.number)) return invalid();"
        ]
    big_endian = int(field.endian == "big")
    return [
        (
            f"if (!read_number(data, payload_end, &offset, {constant(_int_width(field.kind))}, "
            f"{constant(big_endian)}, &{target}.number)) return invalid();"
        )
    ]


def _c_reader_source(
    level: int,
    seed: int,
    magic: bytes,
    version: int,
    count_width: int,
    count_endian: str,
    header_fields: list[Field],
    record_fields: list[Field],
    flags_index: int,
    optional_mask: int,
    checksum_kind: str,
    checksum_modulus: int,
    rolling_key: int,
    rolling_a: int,
    rolling_c: int,
    decode_key: int,
) -> str:
    encoded = level == 4

    def constant(value: int) -> str:
        return c_constant_expression(value, decode_key if encoded else None)

    lines = [
        "#include <inttypes.h>",
        "#include <stdint.h>",
        "#include <stdio.h>",
        "#include <stdlib.h>",
        "",
    ]
    if encoded:
        lines.extend(
            [
                f"static volatile uint32_t decode_key = 0x{decode_key:08X}u;",
                "static int opaque_true(uint32_t value) {",
                '    __asm__ volatile("" : "+r"(value));',
                "    return ((value * value + value) & 1u) == 0u;",
                "}",
                "",
            ]
        )
    lines.extend(
        [
            "typedef struct {",
            "    uint32_t number;",
            "    size_t length;",
            "    unsigned char text[256];",
            "} Value;",
            "",
            "static int invalid(void) {",
            '    puts("INVALID");',
            "    return 1;",
            "}",
            "",
            "static int read_number(const unsigned char *data, size_t end,",
            "                       size_t *offset, unsigned width, int big_endian,",
            "                       uint32_t *output) {",
            "    if (*offset > end || width > end - *offset) return 0;",
            "    uint32_t value = 0;",
            "    if (big_endian) {",
            "        for (unsigned i = 0; i < width; i++)",
            "            value = (value << 8) | data[(*offset)++];",
            "    } else {",
            "        for (unsigned i = 0; i < width; i++)",
            "            value |= (uint32_t)data[(*offset)++] << (8u * i);",
            "    }",
            "    *output = value;",
            "    return 1;",
            "}",
            "",
            "static int read_string(const unsigned char *data, size_t end,",
            "                       size_t *offset, Value *output) {",
            "    if (*offset >= end) return 0;",
            "    size_t length = data[(*offset)++];",
            "    if (length > end - *offset) return 0;",
            "    for (size_t i = 0; i < length; i++) {",
            "        unsigned char byte = data[*offset + i];",
            "        if (byte < 32u || byte > 126u) return 0;",
            "        output->text[i] = byte;",
            "    }",
            "    output->length = length;",
            "    *offset += length;",
            "    return 1;",
            "}",
            "",
            "static int read_varint(const unsigned char *data, size_t end,",
            "                       size_t *offset, uint32_t *output) {",
            "    uint32_t value = 0;",
            "    for (unsigned i = 0; i < 5; i++) {",
            "        if (*offset >= end) return 0;",
            "        unsigned char byte = data[(*offset)++];",
            "        if (i == 4 && (byte & 0xF0u)) return 0;",
            "        value |= (uint32_t)(byte & 0x7Fu) << (7u * i);",
            "        if (!(byte & 0x80u)) {",
            "            if (i && !(byte & 0x7Fu)) return 0;",
            "            *output = value;",
            "            return 1;",
            "        }",
            "    }",
            "    return 0;",
            "}",
            "",
        ]
    )
    if level >= 2:
        checksum_code = {
            "sum32": [
                "    uint32_t result = 0;",
                "    for (size_t i = 0; i < length; i++) result += data[i];",
                "    return result;",
            ],
            "xor32": [
                "    uint32_t result = 0;",
                "    for (size_t i = 0; i < length; i += 4u) {",
                "        uint32_t word = 0;",
                "        for (size_t j = 0; j < 4u && i + j < length; j++)",
                "            word |= (uint32_t)data[i + j] << (8u * j);",
                "        result ^= word;",
                "    }",
                "    return result;",
            ],
            "adler": [
                "    uint32_t first = 1, second = 0;",
                "    for (size_t i = 0; i < length; i++) {",
                "        first = (first + data[i]) % modulus;",
                "        second = (second + first) % modulus;",
                "    }",
                "    return (second << 16) | first;",
            ],
        }[checksum_kind]
        lines.extend(
            [
                "static uint32_t checksum_data(const unsigned char *data, size_t length,",
                "                             uint32_t modulus) {",
                *checksum_code,
                "}",
                "",
            ]
        )
    lines.extend(
        [
            "static void print_json_string(const unsigned char *text, size_t length) {",
            "    putchar('\"');",
            "    for (size_t i = 0; i < length; i++) {",
            "        if (text[i] == '\"' || text[i] == '\\\\') putchar('\\\\');",
            "        putchar(text[i]);",
            "    }",
            "    putchar('\"');",
            "}",
            "",
            "static void print_value(const Value *value, int is_string) {",
            "    if (is_string) print_json_string(value->text, value->length);",
            '    else printf("%" PRIu32, value->number);',
            "}",
            "",
        ]
    )
    lines.extend(
        [
            "int main(int argc, char **argv) {",
            "    if (argc != 2) return invalid();",
            '    FILE *input = fopen(argv[1], "rb");',
            "    if (!input) return invalid();",
            "    if (fseek(input, 0, SEEK_END) != 0) return invalid();",
            "    long file_size_long = ftell(input);",
            "    if (file_size_long < 0 || file_size_long > 65536) return invalid();",
            "    if (fseek(input, 0, SEEK_SET) != 0) return invalid();",
            "    size_t file_size = (size_t)file_size_long;",
            "    unsigned char *data = malloc(file_size ? file_size : 1u);",
            "    if (!data) return invalid();",
            "    if (file_size && fread(data, 1, file_size, input) != file_size)",
            "        return invalid();",
            "    fclose(input);",
            "    size_t payload_end = file_size;",
        ]
    )
    if level >= 2:
        lines.extend(
            [
                "    if (file_size < 4u) return invalid();",
                "    payload_end -= 4u;",
            ]
        )
    lines.extend(
        [
            "    size_t offset = 5u;",
            "    size_t record_start = 0;",
            "    uint32_t record_count = 0;",
            "    Value header_values[3] = {{0}};",
            "    Value record_values[8][5] = {{{0}}};",
            "    int record_present[8][5] = {{0}};",
            f"    if (file_size < 5u + {count_width}u) return invalid();",
            "    uint32_t actual_magic = (uint32_t)data[0] |",
            "        (uint32_t)data[1] << 8 | (uint32_t)data[2] << 16 |",
            "        (uint32_t)data[3] << 24;",
            (
                f"    if (actual_magic != {constant(int.from_bytes(magic, 'little'))}) "
                "return invalid();"
            ),
            f"    if (data[4] != {constant(version)}) return invalid();",
        ]
    )
    if level >= 2:
        lines.extend(
            [
                "    uint32_t stored_checksum = (uint32_t)data[payload_end] |",
                "        (uint32_t)data[payload_end + 1u] << 8 |",
                "        (uint32_t)data[payload_end + 2u] << 16 |",
                "        (uint32_t)data[payload_end + 3u] << 24;",
                (
                    f"    if (checksum_data(data, payload_end, {constant(checksum_modulus)}) "
                    "!= stored_checksum) return invalid();"
                ),
            ]
        )
    header_block = [
        (
            f"if (!read_number(data, payload_end, &offset, {constant(count_width)}, "
            f"{constant(int(count_endian == 'big'))}, &record_count)) return invalid();"
        ),
        "if (record_count > 8u) return invalid();",
    ]
    for index, field in enumerate(header_fields):
        header_block.extend(
            _c_read_field(
                field,
                f"header_values[{index}]",
                constant=constant,
            )
        )
    header_block.append("record_start = offset;")
    if level == 4:
        header_block.extend(
            [
                f"uint32_t rolling_key = {constant(rolling_key)};",
                f"uint32_t rolling_a = {constant(rolling_a)};",
                f"uint32_t rolling_c = {constant(rolling_c)};",
                "for (size_t i = record_start; i < payload_end; i++) {",
                "    data[i] ^= (unsigned char)rolling_key;",
                "    rolling_key = rolling_key * rolling_a + rolling_c;",
                "}",
            ]
        )
    records_block = ["for (size_t row = 0; row < record_count; row++) {"]
    for index, field in enumerate(record_fields):
        if field.optional:
            records_block.append(
                f"    if (!(header_values[{flags_index}].number & "
                f"{constant(optional_mask)})) continue;"
            )
        records_block.extend(
            "    " + line
            for line in _c_read_field(
                field,
                f"record_values[row][{index}]",
                constant=constant,
            )
        )
        records_block.append(f"    record_present[row][{index}] = 1;")
    records_block.append("}")
    records_block.append("if (offset != payload_end) return invalid();")

    output_block = [
        'printf("{\\"header\\":{");',
    ]
    for comma, index in enumerate(
        sorted(range(len(header_fields)), key=lambda item: header_fields[item].name)
    ):
        field = header_fields[index]
        if comma:
            output_block.append("putchar(',');")
        output_block.extend(
            [
                f"printf({json.dumps(chr(34) + field.name + chr(34) + ':')});",
                f"print_value(&header_values[{index}], {int(field.kind == 'str')});",
            ]
        )
    output_block.extend(
        [
            'printf("},\\"records\\":[");',
            "for (size_t row = 0; row < record_count; row++) {",
            "    if (row) putchar(',');",
            "    putchar('{');",
            "    int comma = 0;",
        ]
    )
    for index in sorted(
        range(len(record_fields)), key=lambda item: record_fields[item].name
    ):
        field = record_fields[index]
        output_block.extend(
            [
                f"    if (record_present[row][{index}]) {{",
                "        if (comma) putchar(',');",
                f"        printf({json.dumps(chr(34) + field.name + chr(34) + ':')});",
                (
                    f"        print_value(&record_values[row][{index}], "
                    f"{int(field.kind == 'str')});"
                ),
                "        comma = 1;",
                "    }",
            ]
        )
    output_block.extend(
        [
            "    putchar('}');",
            "}",
            'printf("]}\\n");',
            "return 0;",
        ]
    )
    if level == 4:
        lines.extend(
            emit_c_dispatcher(
                seed,
                [header_block, records_block],
                output_block,
                opaque=True,
                opaque_expression="record_count ^ header_values[0].number",
            )
        )
    else:
        lines.extend("    " + line if line else "" for line in header_block)
        lines.extend("    " + line if line else "" for line in records_block)
        lines.extend("    " + line if line else "" for line in output_block)
    lines.extend(["}", ""])
    return "\n".join(lines)


def _encode_varint(value: int) -> bytes:
    output = bytearray()
    while value > 0x7F:
        output.append((value & 0x7F) | 0x80)
        value >>= 7
    output.append(value)
    return bytes(output)


def _encode_field(field: Field, value: int | str) -> bytes:
    if field.kind == "str":
        raw = str(value).encode("ascii")
        return bytes([len(raw)]) + raw
    if field.kind == "varint":
        return _encode_varint(int(value))
    return int(value).to_bytes(_int_width(field.kind), field.endian)


def _finish_file(
    plain: bytes,
    record_start: int,
    level: int,
    checksum_kind: str,
    checksum_modulus: int,
    rolling_key: int,
    rolling_a: int,
    rolling_c: int,
) -> bytes:
    output = bytearray(plain)
    if level == 4:
        key = rolling_key
        for index in range(record_start, len(output)):
            output[index] ^= key & 0xFF
            key = (key * rolling_a + rolling_c) & MASK
    if level >= 2:
        output.extend(
            _checksum(output, checksum_kind, checksum_modulus).to_bytes(4, "little")
        )
    return bytes(output)


def _make_valid_file(
    rng: random.Random,
    *,
    level: int,
    magic: bytes,
    version: int,
    count_width: int,
    count_endian: str,
    header_fields: list[Field],
    record_fields: list[Field],
    optional_mask: int,
    checksum_kind: str,
    checksum_modulus: int,
    rolling_key: int,
    rolling_a: int,
    rolling_c: int,
    record_count: int | None = None,
    optional_enabled: bool | None = None,
) -> tuple[
    bytes, dict[str, object], bytes, int, dict[tuple[object, ...], tuple[int, int]]
]:
    if record_count is None:
        record_count = rng.randint(0, 8)
    header: dict[str, int | str] = {}
    plain = bytearray(magic)
    plain.append(version)
    plain.extend(record_count.to_bytes(count_width, count_endian))
    offsets: dict[tuple[object, ...], tuple[int, int]] = {}
    for field in header_fields:
        if field.name == "flags" and level >= 3:
            value = rng.getrandbits(8)
            if optional_enabled:
                value |= optional_mask
            else:
                value &= ~optional_mask
        else:
            value = _random_value(rng, field.kind)
        start = len(plain)
        plain.extend(_encode_field(field, value))
        offsets[("header", field.name)] = (start, len(plain))
        header[field.name] = value
    record_start = len(plain)
    records: list[dict[str, int | str]] = []
    for row in range(record_count):
        record: dict[str, int | str] = {}
        for field in record_fields:
            if field.optional and not (
                level >= 3 and int(header["flags"]) & optional_mask
            ):
                continue
            value = _random_value(rng, field.kind)
            start = len(plain)
            plain.extend(_encode_field(field, value))
            offsets[("record", row, field.name)] = (start, len(plain))
            record[field.name] = value
        records.append(record)
    completed = _finish_file(
        bytes(plain),
        record_start,
        level,
        checksum_kind,
        checksum_modulus,
        rolling_key,
        rolling_a,
        rolling_c,
    )
    reference = {"header": header, "records": records}
    return completed, reference, bytes(plain), record_start, offsets


def _random_value(rng: random.Random, kind: str) -> int | str:
    if kind == "str":
        return "".join(rng.choice(STRING_ALPHABET) for _ in range(rng.randint(1, 16)))
    if kind == "u8":
        return rng.getrandbits(8)
    if kind == "u16":
        return rng.getrandbits(16)
    return rng.getrandbits(32)


def _make_fields(rng: random.Random, level: int) -> tuple[list[Field], list[Field]]:
    header_count = rng.randint(1, 3)
    record_count = rng.randint(2, 5)
    numeric_kinds = ("u8", "u16", "u32")
    kinds = numeric_kinds if level == 0 else (*numeric_kinds, "str")
    if level >= 3:
        kinds = (*kinds, "varint")

    def endian() -> str:
        return rng.choice(("little", "big")) if level >= 1 else "little"

    header_names: list[str] = []
    if level >= 3:
        header_names.append("flags")
    header_names.extend(
        rng.sample(
            [name for name in FIELD_NAMES if name != "flags"],
            header_count - len(header_names),
        )
    )
    header_fields = [
        Field(
            name,
            rng.choice(numeric_kinds) if name == "flags" else rng.choice(kinds),
            endian(),
        )
        for name in header_names
    ]
    record_names = rng.sample(FIELD_NAMES, record_count)
    record_kinds = [rng.choice(kinds) for _ in record_names]
    if level >= 1:
        record_kinds[0] = "str" if level < 3 else "varint"
        if level >= 3 and len(record_kinds) > 1:
            record_kinds[1] = "str"
    record_fields = [
        Field(name, kind, endian()) for name, kind in zip(record_names, record_kinds)
    ]
    if level >= 3:
        record_fields[-1] = Field(
            record_fields[-1].name,
            record_fields[-1].kind,
            record_fields[-1].endian,
            optional=True,
        )
    return header_fields, record_fields


def _reference_parse(source: str, data: bytes) -> object:
    namespace: dict[str, object] = {}
    exec(compile(source, "<trusted-formats-reference>", "exec"), namespace)  # noqa: S102
    return namespace["parse"](data)  # type: ignore[operator]


def generate(seed: int, level: int) -> FormatsInstance:
    if level not in range(5):
        raise ValueError(f"unsupported formats level: {level}")
    rng = random.Random(seed ^ (level * 0x9E3779B9) ^ 0x243F6A88)
    magic = bytes(rng.getrandbits(8) for _ in range(4))
    version = rng.randint(1, 255)
    count_width = rng.choice((2, 4))
    count_endian = rng.choice(("little", "big")) if level >= 1 else "little"
    header_fields, record_fields = _make_fields(rng, level)
    flags_index = next(
        (index for index, field in enumerate(header_fields) if field.name == "flags"),
        0,
    )
    optional_bit = rng.randrange(8)
    optional_mask = 1 << optional_bit
    checksum_kind = rng.choice(("sum32", "xor32", "adler"))
    checksum_modulus = rng.randint(251, 65521)
    rolling_key = rng.getrandbits(32) | 1
    rolling_a = rng.getrandbits(32) | 1
    rolling_c = rng.getrandbits(32)
    decode_key = rng.getrandbits(32) | 1
    if decode_key == rolling_key:
        decode_key ^= 0xA5A5A5A5
    spec: dict[str, object] = {
        "level": level,
        "magic": magic,
        "version": version,
        "count_width": count_width,
        "count_endian": count_endian,
        "header_fields": [_field_to_dict(field) for field in header_fields],
        "record_fields": [_field_to_dict(field) for field in record_fields],
        "flags_index": flags_index,
        "optional_mask": optional_mask,
        "checksum_kind": checksum_kind,
        "checksum_modulus": checksum_modulus,
        "rolling_key": rolling_key,
        "rolling_a": rolling_a,
        "rolling_c": rolling_c,
    }
    c_source = _c_reader_source(
        level,
        seed,
        magic,
        version,
        count_width,
        count_endian,
        header_fields,
        record_fields,
        flags_index,
        optional_mask,
        checksum_kind,
        checksum_modulus,
        rolling_key,
        rolling_a,
        rolling_c,
        decode_key,
    )
    reference_source = _reference_source(spec)

    def make_file(
        file_rng: random.Random,
        count: int | None = None,
        optional_enabled: bool | None = None,
    ):
        return _make_valid_file(
            file_rng,
            level=level,
            magic=magic,
            version=version,
            count_width=count_width,
            count_endian=count_endian,
            header_fields=header_fields,
            record_fields=record_fields,
            optional_mask=optional_mask,
            checksum_kind=checksum_kind,
            checksum_modulus=checksum_modulus,
            rolling_key=rolling_key,
            rolling_a=rolling_a,
            rolling_c=rolling_c,
            record_count=count,
            optional_enabled=optional_enabled,
        )

    sample_rng = random.Random(seed ^ (level * 0xBB67AE85) ^ 0x3C6EF372)
    sample_a = make_file(sample_rng, 2, True if level >= 3 else None)[0]
    sample_b = make_file(sample_rng, 4, False if level >= 3 else None)[0]
    files: dict[str, bytes] = {
        "samples/a.bin": sample_a,
        "samples/b.bin": sample_b,
    }
    if level == 0:
        files["reader.c"] = c_source.encode("utf-8")
    expected_files = (
        ["reader.c", "reader", "samples/a.bin", "samples/b.bin"]
        if level == 0
        else ["reader", "samples/a.bin", "samples/b.bin"]
    )
    protected_hashes = {
        path: hashlib.sha256(content).hexdigest() for path, content in files.items()
    }

    hidden_files: list[bytes] = []
    seen = {sample_a, sample_b}
    hidden_rng = random.Random(seed ^ (level * 0x94D049BB) ^ 0x510E527F)
    while len(hidden_files) < 38:
        index = len(hidden_files)
        count = 0 if index == 0 else hidden_rng.randint(1, 8)
        optional_enabled = bool(index & 1) if level >= 3 else None
        candidate = make_file(hidden_rng, count, optional_enabled)[0]
        if candidate not in seen:
            seen.add(candidate)
            hidden_files.append(candidate)

    def distinct_invalid(candidate: bytes) -> None:
        if candidate not in seen:
            seen.add(candidate)
            hidden_files.append(candidate)

    def fresh_base(
        *,
        count: int = 2,
        optional_enabled: bool | None = None,
    ):
        return make_file(hidden_rng, count, optional_enabled)

    mutation_bases = [fresh_base()[0] for _ in range(12)]
    mutation_ops = ["bad_magic", "wrong_version", "truncated", "trailing"] * 3
    if level == 1:
        mutation_ops = ["bad_magic", "wrong_version", "truncated", "trailing"] * 2
        mutation_ops.extend(["nonprintable"] * 4)
    elif level == 2:
        mutation_ops = ["bad_magic", "wrong_version", "truncated", "trailing"] * 2
        mutation_ops.extend(["bad_checksum"] * 2)
        mutation_ops.extend(["nonprintable"] * 2)
    elif level >= 3:
        mutation_ops = ["bad_magic", "wrong_version", "truncated", "trailing"]
        mutation_ops.extend(["bad_checksum"] * 2)
        mutation_ops.extend(["nonprintable"] * 2)
        mutation_ops.extend(["flipped_flag", "varint_overrun"])
        mutation_ops.extend(["bad_magic", "wrong_version"])
    for operation, base in zip(mutation_ops, mutation_bases, strict=True):
        candidate = base
        if operation == "bad_magic":
            candidate = bytes([base[0] ^ 1]) + base[1:]
        elif operation == "wrong_version":
            candidate = base[:4] + bytes([base[4] ^ 1]) + base[5:]
        elif operation == "truncated":
            candidate = base[:-1]
        elif operation == "trailing":
            candidate = base + b"\x7f"
        elif operation == "bad_checksum":
            candidate = base[:-1] + bytes([base[-1] ^ 1])
        elif operation == "nonprintable":
            _, _, plain, record_start, offsets = fresh_base(
                count=1, optional_enabled=True
            )
            field = next(field for field in record_fields if field.kind == "str")
            start, _ = offsets[("record", 0, field.name)]
            changed = bytearray(plain)
            changed[start + 1] = 0
            candidate = _finish_file(
                bytes(changed),
                record_start,
                level,
                checksum_kind,
                checksum_modulus,
                rolling_key,
                rolling_a,
                rolling_c,
            )
        elif operation == "flipped_flag":
            _, _, plain, record_start, offsets = fresh_base(
                count=1, optional_enabled=True
            )
            start, end = offsets[("header", "flags")]
            flags_field = header_fields[flags_index]
            old_value = int.from_bytes(plain[start:end], flags_field.endian)
            changed = bytearray(plain)
            changed[start:end] = (old_value ^ optional_mask).to_bytes(
                end - start, flags_field.endian
            )
            candidate = _finish_file(
                bytes(changed),
                record_start,
                level,
                checksum_kind,
                checksum_modulus,
                rolling_key,
                rolling_a,
                rolling_c,
            )
        elif operation == "varint_overrun":
            _, _, plain, record_start, offsets = fresh_base(count=1)
            field = next(field for field in record_fields if field.kind == "varint")
            start, end = offsets[("record", 0, field.name)]
            changed = plain[:start] + (b"\x80" * 6) + plain[end:]
            candidate = _finish_file(
                changed,
                record_start,
                level,
                checksum_kind,
                checksum_modulus,
                rolling_key,
                rolling_a,
                rolling_c,
            )
        distinct_invalid(candidate)
    if len(hidden_files) != 50:
        raise RuntimeError("formats hidden-case generation did not produce 50 files")

    sample_output = canonical_json(_reference_parse(reference_source, sample_a))
    raw_constants = [int.from_bytes(magic, "little")]
    if level >= 2:
        raw_constants.append(checksum_modulus)
    if level == 4:
        raw_constants.extend((rolling_key, rolling_a, rolling_c))
    return FormatsInstance(
        seed=seed,
        level=level,
        files=files,
        expected_files=expected_files,
        protected_hashes=protected_hashes,
        c_source=c_source,
        reference_source=reference_source,
        sample_a=sample_a,
        sample_a_output=sample_output,
        hidden_files=hidden_files,
        valid_count=38,
        raw_constants=raw_constants,
        format_spec=spec,
    )


def generate_test_files(instance: FormatsInstance, count: int = 200) -> list[bytes]:
    spec = instance.format_spec
    header_fields = [Field(**field) for field in spec["header_fields"]]
    record_fields = [Field(**field) for field in spec["record_fields"]]
    rng = random.Random(instance.seed ^ (instance.level * 0xD1B54A35) ^ 0x6C8E9CF5)
    files = []
    for index in range(count):
        raw = _make_valid_file(
            rng,
            level=instance.level,
            magic=spec["magic"],
            version=spec["version"],
            count_width=spec["count_width"],
            count_endian=spec["count_endian"],
            header_fields=header_fields,
            record_fields=record_fields,
            optional_mask=spec["optional_mask"],
            checksum_kind=spec["checksum_kind"],
            checksum_modulus=spec["checksum_modulus"],
            rolling_key=spec["rolling_key"],
            rolling_a=spec["rolling_a"],
            rolling_c=spec["rolling_c"],
            record_count=rng.randint(0, 8),
            optional_enabled=bool(index & 1) if instance.level >= 3 else None,
        )[0]
        if index & 1:
            mutation = index % 4
            if mutation == 1:
                raw = bytes([raw[0] ^ 1]) + raw[1:]
            elif mutation == 3:
                raw = raw[:-1]
            elif instance.level >= 2:
                raw = raw[:-1] + bytes([raw[-1] ^ 1])
            else:
                raw += b"\x7f"
        files.append(raw)
    return files
