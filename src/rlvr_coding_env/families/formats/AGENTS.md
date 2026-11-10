# families/formats: write `parser.py` for a generated binary format

Agent gets a runnable `reader` and two sample files, implements `parse(data: bytes)`. Grading via `common/` (see `../common/AGENTS.md`). Return is a JSON dict (str keys; int/str/None/list/dict values) or `None` for invalid files. Inputs arrive as bytes decoded from hex.

## Levels
L0 fixed-width little-endian, `-O0`. L1 per-field endianness + ASCII strings. L2 stripped `-O2` + checksum. L3 ULEB128 + flag-gated optional fields. L4 rolling-XOR payload + flattening + encoded constants.

## Invariants
- 50 hidden files per task: 38 valid, 12 invalid (bad magic, truncation, trailing bytes, bad checksum, bad varints/flags). Reward needs ALL correct; `valid_pass_frac`/`invalid_pass_frac` are metrics only.
- C reader, Python reference parser and file builders in `generator.py` must agree. Output is canonical JSON via `canonical_json` (also used by `qc/seed_sweep.py`).
- L3/L4 reuse `decompile.generator` emitters.
- `generator.py` is about 1000 lines; change one layer at a time (field kinds, encoding, C emission, negatives).
- The runnable `reader` is a black-box oracle; one observed L4 episode used it for differential testing. Limiting it is a design decision.

## Writing and testing changes
- Generator/reference/prompt: `uv run pytest tests/test_formats.py -q`, then once at the end `vf-validate formats` at a level you touched (L0 and L4 if unsure).
- Taskset staging or grading: add `uv run python qc/run_formats_attacks.py` (Docker, expect 64/64).
- gcc/strip-gated tests skip on Windows.
