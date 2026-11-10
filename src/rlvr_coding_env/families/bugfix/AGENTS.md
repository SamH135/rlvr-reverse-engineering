# families/bugfix: warm-up/calibration family

Agent fixes planted bugs in `lib.py`. L1: one buggy function, failing visible test. L2: two functions from different templates, visible tests pass, hidden tests catch both.

## Differs from common (don't assume shared behavior)
- Own `runner.py` and own grading in `taskset.py::_compute_grading`; does NOT use `common/`.
- Scope is an EXACT file set (`protected` paths + `lib.py`); extra files score 0. `__pycache__`/`.pytest_cache` ignored. No cleanup step, no audit hook. Runner path hardcoded `/app/repo/lib.py`.
- Compares `json.dumps(sort_keys=True)`; `1.0` vs `1` still differ. Also runs `tests/test_visible.py` -> `visible_pass` (metric only).

## Generator invariants (checked by `tests/test_generator.py`)
- 50 hidden cases per target function, none equal to a visible input; reference never errors on them; buggy differs from reference on at least one.
- L1: visible test fails on buggy code. L2: visible tests pass, at most 2 visible cases, distinct templates and function names.
- Deterministic per `(seed, level)`. New templates go in `templates.py` and must satisfy all of this for seeds 0-199.

## Writing and testing changes
- Templates/generator: `uv run pytest tests/test_generator.py -q` (~30s; the 200-seed sweep is marked `slow`, so name the file explicitly or use `-m slow` — `-m "not slow"` skips it). That is enough for template-only changes.
- Taskset or `runner.py` (scope, grading): the pytest file above, then once at the end `uv run python qc/run_attacks.py` (Docker, expect 26/26). Add `--level 2` only if L2 behavior changed.
