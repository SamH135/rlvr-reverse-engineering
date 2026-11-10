# families/decompile: write `solution.py` reimplementing a generated uint32 C program

Maps a list of uint32 to a uint32. Grading via `common/` (see `../common/AGENTS.md`); return must be exact `int` in `[0, 2**32)`.

## Levels
L0 C source + `-O0` binary. L1 `-O0` binary only. L2 stripped `-O2`. L3 control-flow flattening. L4 L3 + opaque predicates + XOR-encoded constants. Stage counts: `STAGES_PER_LEVEL` in `generator.py`.

## Invariants
- Python reference and C program come from one seed and must agree on all hidden inputs.
- `c_constant_expression` and `emit_c_dispatcher` are imported by `formats/generator.py`; changing their output affects formats L3/L4.
- The provided executable is runnable by the agent (black-box oracle). Grading deletes it and the audit hook blocks running it.
- Cases are `[example, *hidden_inputs]`.

## Writing and testing changes
- Generator/reference: `uv run pytest tests/test_decompile.py -q`, then once at the end `vf-validate decompile` at a level you touched.
- Taskset staging: add `uv run python qc/run_decompile_attacks.py` (Docker, expect 68/68).
- Touched the shared emitters: also `uv run pytest tests/test_formats.py -q` and `vf-validate formats` at L3 or L4. The formats attack suite only if you changed C emission semantics.
