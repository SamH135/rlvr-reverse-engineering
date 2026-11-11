# families/keygen: write `keygen(name) -> str` accepted by a generated checker

Deliverable `keygen.py`. Grading via `common/` (see `../common/AGENTS.md`).

## Levels
L0 readable `check.py`. L1 `check.c` + `-O0` binary. L2 `-O0` binary only. L3 stripped `-O2`. L4 L3 + XOR-encoded constants. L5 8 ops as `noinline` functions via a pointer table. L6 ops as bytecode for an embedded VM (per-seed opcode permutation, XOR-encoded immediates).

## Invariants
- `generator.py` builds the Python `reference_source`, the C checker, example and hidden names from one `random.Random(seed)`. C and Python must agree for every name; change both together.
- Adjacent `table` ops are forbidden in `_parameters`: `h ^= T(c,i)` twice cancels to a name-independent serial.
- Names are 3-16 `[A-Za-z0-9]`; the prompt in `taskset.py` states this, keep them consistent.
- The binary is built in the sandbox in `setup()`; protected hashes cover provided files, so builds must be deterministic.
- Cases are `[example, *hidden_names]`; expected values come from `exec`ing `reference_source` on the host. `validate()` must score 1.0.
- The agent can run `./check`: a black-box oracle (known ceiling-effect risk). Removing it is a design decision.

## Writing and testing changes
- Generator/reference/prompt: `uv run pytest tests/test_keygen.py -q`, then once at the end `vf-validate keygen` at the level you changed.
- Build or taskset staging (`setup`, `stage_verifier`): the above plus `uv run python qc/run_keygen_attacks.py` (Docker, expect 56/56).
- gcc-gated tests skip on Windows; they run on Linux CI.
- The deliverable stub keygen.py is pre-created by setup(), is agent-editable and is NOT covered by protected hashes or expected files.
