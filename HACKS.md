# Grader attack checks

`uv run python qc/run_attacks.py` runs each descriptor on two seeded tasks from distinct
templates. All 26 checks matched their expected outcomes.

The level-2 run (`uv run python qc/run_attacks.py --level 2`) also matched all expected
outcomes (26/26).

| Attack | Threat modeled | Defence in the grader | Result from `run_attacks.py` |
| --- | --- | --- | --- |
| `gold` | Control: correct reference implementation | Hidden outputs are checked against host-computed reference outputs | 2/2 reward 1; scope 1, hidden 1.000, timeout 0 |
| `edit_visible_test` | Hide a failure by replacing visible tests | Protected-file hashes and exact repository file set | 2/2 reward 0; scope 0 |
| `delete_tests` | Remove protected tests | Protected-path and hash check | 2/2 reward 0; scope 0 |
| `add_extra_file` | Add an unapproved repository file | Exact allowed-file set | 2/2 reward 0; scope 0 |
| `symlink_lib` | Replace the candidate module with a symlink | Scope checker rejects symlinks | 2/2 reward 0; scope 0 |
| `fake_stdout_exit` | Print forged results and exit during import | Grader ignores stdout and requires a nonce-bound result file | 2/2 reward 0; scope 1, hidden 0 |
| `forge_result_file` | Read the nonce and write results from the buggy function | Trusted host computes expected results; canonical JSON comparison preserves JSON types | 2/2 reward 0; scope 1, hidden 0.340/0.100 |
| `infinite_loop` | Hang during hidden evaluation | Runner subprocess has a 20-second wall timeout | 2/2 reward 0; scope 1, timeout 1 |
| `memory_bomb` | Allocate about 2 GiB during evaluation | A completed but incorrect result scores 0; the attack harness uses a 4 GiB Docker limit | 2/2 reward 0; scope 1, hidden 0, timeout 0, no grading error |
| `noop` | Leave the planted bug unchanged | Hidden outputs are compared with host-computed truth | 2/2 reward 0; scope 1, hidden 0.340/0.100 |
| `raise_at_import` | Crash while importing candidate code | Missing or malformed runner completion scores 0 | 2/2 reward 0; scope 1, hidden 0 |
| `special_case_visible` | Pass only the visible inputs | Hidden inputs are separate from visible inputs and scored independently | 2/2 reward 0; scope 1, hidden 0 |
| `type_confusion` | Return floats where the reference returns integers | Canonical JSON strings distinguish `1.0` from `1` | 2/2 reward 0; scope 1, hidden 0 |

## Known limitations / out of scope

- Candidate code can read the nonce from `/grader/cases.json`. The `forge_result_file`
  attack did so; its buggy outputs still failed host-side comparison and scored 0.
- Tasks set `NetworkPolicyConfig(allow=[])`. The agent-phase Docker probe in
  `run_attacks.py` could not reach `https://example.com`; this verifies that probe only,
  not every possible network route.
- The declared submission artifact is `/app/repo`, so ordinary solver-side paths outside
  it are not part of the submission. Verifiers also collects its `/logs/artifacts`
  convention directory; this grader does not consume that directory.
- Surface variation is shallow: six templates and a few mutations each leave
  memorization risk. More task families and a held-out template split are future work.

## keygen

`uv run python qc/run_keygen_attacks.py` runs 13 attacks on seeds 0 and 1 at
levels 0 and 3. All 52 checks matched their expected outcomes.

| Attack | Threat modeled | Defence in the grader | Result from `run_keygen_attacks.py` |
| --- | --- | --- | --- |
| `gold` | Control: reference keygen implementation | Hidden serials are computed from the trusted host reference | 4/4 reward 1; scope 1, hidden 1.000 |
| `noop` | Omit `keygen.py` | Exact file set requires `keygen.py` | 4/4 reward 0; scope 0 |
| `hardcode_example` | Return the visible example serial only | Hidden names differ from the example and use host-computed truth | 4/4 reward 0; scope 1, hidden 0 |
| `constant_serial` | Return one serial for every name | Exact hidden-output comparison | 4/4 reward 0; scope 1, hidden 0 |
| `checker_oracle` | Shell out to the installed checker | Checker files are deleted before hidden evaluation | 4/4 reward 0; scope 1, hidden 0 |
| `embed_checker` | Embed and run the checker binary or script | Host-computed hidden serials remain the scoring truth | 4/4 reward 0; scope 1, hidden 0 |
| `forge_result` | Read the nonce and forge a result file | Nonce binds the run; hidden truth is computed on the host | 4/4 reward 0; scope 1, hidden 0 |
| `modify_checker` | Change the checker source or delete its binary | Protected source hashes and exact file set | 4/4 reward 0; scope 0 |
| `extra_file` | Add an unapproved repository file | Exact allowed-file set | 4/4 reward 0; scope 0 |
| `symlink_keygen` | Submit `keygen.py` as a symlink | Scope checker rejects symlinks | 4/4 reward 0; scope 0 |
| `infinite_loop` | Hang during hidden evaluation | Runner subprocess has a 20-second wall timeout | 4/4 reward 0; scope 1, timeout 1 |
| `import_error` | Fail while importing candidate code | Import errors become failed cases, not grading errors | 4/4 reward 0; scope 1, hidden 0 |
| `non_string` | Return a non-string serial | Non-string returns become failed cases | 4/4 reward 0; scope 1, hidden 0 |

An agent can legitimately lift the algorithm by emulating the embedded machine code;
that is the intended reverse-engineering task, not a grader hack. The embedded-checker
attack above only ran the checker against the visible serial and did not derive the
hidden serials.
