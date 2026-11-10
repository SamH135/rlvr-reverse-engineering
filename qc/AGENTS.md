# qc: adversarial grader checks

Each `run_*_attacks.py` subclasses the family task, applies a JSON descriptor from `*_attackers/`, grades in Docker, and asserts `expected_reward`. Needs Docker and image `rlvr-keygen:0.1`. Threats and defenses: `../HACKS.md`.

| Suite | Command (`uv run python ...`) | Expected |
| --- | --- | --- |
| bugfix | `qc/run_attacks.py` (`--level 2` for L2) | 26/26 each |
| keygen | `qc/run_keygen_attacks.py` | 56/56 |
| decompile | `qc/run_decompile_attacks.py` | 68/68 |
| formats | `qc/run_formats_attacks.py` | 64/64 |

## Rules
- `gold` and `gold_with_scratch` must score 1; every other attacker 0. A passing exploit is a grader bug: fix the grader, never the expectation.
- Run only the suite for the family you changed (all four only for `common/` changes). Run once at the end, not per edit.
- New exploit: add `*_attackers/<name>.json`, run that suite, add a `HACKS.md` row, update counts in `HACKS.md` and `README.md`.
- `seed_sweep.py` is host-side (no Docker), rewrites `REPORT.md`; run it only when generators change materially. `--docker-result` just records results you already have.
- Interrupted runs can leave `vf-*` containers; check `docker ps` before trusting a clean state.
