# AGENTS.md

Seed-generated RLVR coding environment on Verifiers v1 (`verifiers.v1`). Four task
families (bugfix, keygen, decompile, formats), levels L0-L4, binary reward. Agents
edit one deliverable; a fresh sandbox grades it against host-computed truth.
Design rationale: `docs/DESIGN.md`. Threat model and attack results: `HACKS.md`.

## Commands
`uv`/`python` are not on PATH on the Windows dev host: use `py -m uv ...` there, `uv ...` elsewhere.
- Install: `uv sync`. Image (Docker running): `docker build -f docker/keygen.Dockerfile -t rlvr-keygen:0.1 .`
- Tests: `uv run pytest -q -m "not slow"` (fast suite; gcc/objdump/strip tests skip when absent, e.g. Windows). `uv run pytest -q` adds the `slow` marker (multi-seed sweeps). One file: `uv run pytest tests/test_x.py -q`
- Lint: `uv run ruff check .`
- Validate one family/level: `uv run vf-validate <family> --runtime.type docker --taskset.level <n> -n 3`
- Attack suites (Docker, minutes): `qc/run_attacks.py [--level 2]`, `qc/run_keygen_attacks.py`, `qc/run_decompile_attacks.py`, `qc/run_formats_attacks.py` (all `uv run python ...`)
- Transcript viewer: `uv run python tools/view_transcripts.py [outputs|<run-dir>] [-o out.html] [--open]` — renders `traces.jsonl` rollouts to one self-contained HTML

## Which checks to run (keep it small; do not repeat runs)
1. Always, fast: `ruff check` plus the pytest file for the area you touched.
2. Once, at the end, only if you changed a generator, taskset, prompt-affecting logic or a family runner: that ONE family's attack suite, or `vf-validate` for that family at one level you touched.
3. Once, at the end, only if you changed `families/common/` (runner, scope, hook, grading): all four attack suites.
Docs, comments, baselines scripts: step 1 only (docs: nothing). Do not re-run Docker suites after each edit, and do not run the full pytest suite unless you touched shared code.
If Docker is unavailable, say so in your report; do not skip silently.

## Layout
- `src/rlvr_coding_env/families/common/` shared grader: `grading.py` (host), `runner.py` (shipped into sandbox)
- `src/rlvr_coding_env/families/{bugfix,keygen,decompile,formats}/` generator + taskset per family
- `src/{bugfix,keygen,decompile,formats}/` 3-line re-exports so `vf-run <name>` resolves; match `[tool.hatch]` packages in `pyproject.toml`
- `src/fcntl.py` Windows-only shim (verifiers imports `fcntl`); POSIX uses stdlib
- `qc/` attack suites; `baselines/` model runs; `tests/` pytest; `docker/` task image; `tools/` dev utilities (transcript viewer)

## Navigation: read the local AGENTS.md before editing
`families/common/`, `families/<family>/`, `qc/`, `baselines/`, `tests/` each have one.

## Invariants
- Reward is exactly 0.0 or 1.0 (`solved`). Fractions are `@vf.metric` only; never add partial reward.
- Expected outputs come from the host-side `reference_source`; never trust more than raw outputs from the sandbox.
- Fail closed: scope violation, exception, bad type, timeout, nonce mismatch, wrong case count all score 0.
- `generate(seed, level)` is deterministic: only `random.Random(seed)`; never global `random`, time or `secrets` in generators.
- Train seeds < `EVAL_SEED_BASE` (1,000,000); eval seeds start there.
- Never commit secrets; `src/.env` stays gitignored.

## Boundaries
- Ask first: changing reward semantics, scope rules, the audit-hook deny list, or the level ladder.
- Never: delete/skip/weaken a test or attacker to get green; edit `outputs/` or `baselines/logs/`.

## Maintenance
- Learned something non-obvious about a directory? Update its `AGENTS.md` in the same change; fix any line you made false.
- Report test results honestly, including failures and skips.
- Bug fix: add a regression test that fails before the fix. New exploit: add a `qc/*_attackers/` descriptor and a `HACKS.md` row.
- Provider/API errors are not agent failures; report separately (DESIGN decision 11).
