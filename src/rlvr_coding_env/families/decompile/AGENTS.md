# families/decompile: write `solution.py` reimplementing a generated uint32 C program

Maps a list of uint32 to a uint32. Grading via `common/` (see `../common/AGENTS.md`); return must be exact `int` in `[0, 2**32)`.

## Levels
L0 C source + `-O0` binary. L1 `-O0` binary only. L2 stripped `-O2`. L3 control-flow flattening. L4 L3 + opaque predicates + XOR-encoded constants. L5 8 stages as `noinline` functions behind a pointer table (L4 protections kept). L6 stages compiled to bytecode for an embedded VM (per-seed opcodes, XOR-encoded immediates). L7 L5 plus 4 executed-but-inert `decoy_*` stages interleaved in a 12-entry pointer table and 3 misleading volatile strings; per seed the real program (stages, constants, key, inputs, reference_source) is identical at L5 and L7 for a decoys-on/off ablation. L8 L5-style pointer-table program whose 6 stages include one each of `xtea`, `crc` and `rc4` per-seed crypto stages. Stage counts: `STAGES_PER_LEVEL` in `generator.py`.

## Invariants
- Python reference and C program come from one seed and must agree on all hidden inputs.
- L8 crypto stage semantics are defined by `CRYPTO_HELPERS_PY` (prepended to the L8 `reference_source` only); the C emission must match it exactly.
- `generate` re-rolls the stage list until `f` varies over hidden inputs (only "fold" stages mix xs into acc); healthy seeds keep identical output.
- `c_constant_expression` and `emit_c_dispatcher` are imported by `formats/generator.py`; changing their output affects formats L3/L4.
- The provided executable is runnable by the agent (black-box oracle). Grading deletes it and the audit hook blocks running it.
- Cases are `[example, *hidden_inputs]`.

## Writing and testing changes
- Generator/reference: `uv run pytest tests/test_decompile.py -q`, then once at the end `vf-validate decompile` at a level you touched.
- Taskset staging: add `uv run python qc/run_decompile_attacks.py` (Docker, expect 68/68).
- Touched the shared emitters: also `uv run pytest tests/test_formats.py -q` and `vf-validate formats` at L3 or L4. The formats attack suite only if you changed C emission semantics.
- The deliverable stub solution.py is pre-created by setup(), is agent-editable and is NOT covered by protected hashes or expected files.
- Optional access mode: `access='blackbox'` (level >= 2) makes the binary execute-only (root-owned 0111, static-linked, agent runs as 'agent'); not covered by protected hashes.
