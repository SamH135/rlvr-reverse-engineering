# tests

Flat layout: `conftest.py` (`FakeRuntime` factory for `common/grading.py`),
`test_grading.py` (grader unit tests, no Docker), `test_rewards.py` (`solved`
per family), `test_common_runner.py` (runner audit hook, return types, hex/JSON),
`test_determinism.py` + `test_golden.py` (generator determinism, seed-0 sha256
goldens), `test_properties.py` (hypothesis), `test_smoke.py` (`slow`),
`test_generator.py` (bugfix generator and runner), `test_keygen.py`,
`test_decompile.py`, `test_formats.py`, `test_splits.py`.

## Commands
- Fast suite: `uv run pytest -q -m "not slow"`. Full suite (adds `slow`
  multi-seed sweeps): `uv run pytest -q`. One file: `uv run pytest tests/test_x.py -q`.
- Coverage: `uv run pytest --cov=rlvr_coding_env -m "not slow"`.
- Regenerate goldens only on purpose:
  `RLVR_UPDATE_GOLDEN=1 uv run pytest tests/test_golden.py`.

## Which file for which change
- `common/grading.py`: `test_grading.py` (+ `conftest.py` `FakeRuntime`).
- Runner, scope, hook: `test_common_runner.py` (+ `test_keygen.py` for scope).
- `solved` / reward logic: `test_rewards.py`, `test_properties.py`.
- A family generator or taskset: that family's file. Bugfix: `test_generator.py`. Seed or split logic: `test_splits.py`.
- Generator drift: `test_determinism.py`, `test_golden.py`.

## Writing tests
- Runner/scope tests run `runner.py` as a subprocess with `RLVR_REPO_ROOT` set to a tmp dir; reuse `_run_submission` in `test_common_runner.py`.
- Grader tests drive `FakeRuntime` (`conftest.py`); no async plugin, use `asyncio.run`.
- Tools-gated tests use `skipif(shutil.which(...) is None)` for gcc/strip/objdump/strings. Keep the guards; they run on Linux CI.
- `test_generator.py`'s 200-seed sweep is marked `slow`; keep new tests off that path unless they need the sweep.
- No Docker in pytest; Docker checks live in `../qc/`.
