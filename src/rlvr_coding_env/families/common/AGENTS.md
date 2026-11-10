# families/common: shared grader for keygen, decompile, formats

Not used by bugfix (own runner). Rationale: `docs/DESIGN.md` decisions 4, 6, 7, 8.

## Contract
- `runner.py` is copied verbatim into the sandbox at `/grader/runner.py` by each taskset's `stage_verifier`. Keep it stdlib-only and single-file.
- Modes: `--scope protected.json` prints `{"scope_ok": bool}`; `--run cases.json result.json` writes `{"nonce", "outputs"}`. Honours `RLVR_REPO_ROOT` (default `/app/repo`) so it runs on the host.
- `cases.json` keys: `nonce`, `deliverable`, `function_name`, `return_type` (`str`|`uint32`|`json`), `cases`, optional `arg_decode: "hex"`. `protected.json` keys: `deliverable`, `expected_files`, `hashes`. Renaming a key means editing every taskset's `stage_verifier`.
- `grading.py::grade_function`: scope -> runner -> canonical-JSON compare (`sort_keys`, compact separators, `allow_nan=False`) to host `expected_outputs`. Case 0 is the visible example; 1+ are hidden.
- Order is load-bearing: scope check -> cleanup (delete all but the deliverable) -> audit hook -> import candidate.

## Rules
- Exact return types: `str`; `type(v) is int` in uint32 range (no bool); JSON dict or `None` with str keys and int/str/None/list/dict values (no float/bool).
- Caps: deliverable 16 KiB; result 1,000,000 bytes (defined in both files, keep equal); runner 20s, exit 124/137 = timeout.
- Extra files pass scope and are deleted before import. Don't revert to an exact file set (DESIGN decision 7).
- Audit hook denies process creation, `ctypes`/`mmap`/`cffi`/`_posixsubprocess`, `/proc` opens, rewriting `__code__`/`__closure__`/`__defaults__`. Loosening it reopens binary-wrap. A pure-Python emulator of the binary is legitimate.
- Runner errors become `{"ok": False}` cases, never crashes.

## Writing and testing changes
- Edited `runner.py` or `grading.py`: `uv run pytest tests/test_common_runner.py tests/test_keygen.py -q`, then once at the end all four attack suites (Docker).
- Only added a type or hook rule: add a case to `tests/test_common_runner.py` (reuse `_run_submission`); then the same end-of-work attack run.
- Gap: `grade_function` has no host unit test; the attack suites are its only coverage.
