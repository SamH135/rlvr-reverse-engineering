# Multi-seed QC report

Host-side generated-program checks; no Docker runtime or model was used.
Train seeds: 0–99; eval seeds: 1,000,000–1,000,019. Each family/level cell covers 120 tasks.
Sweep runtime: 1m 38.2s (98.2s).

| Family | Level | Tasks checked | Failed tasks | Median `objdump -d` lines |
| --- | ---: | ---: | ---: | ---: |
| keygen | 0 | 120 | 0 | n/a |
| keygen | 1 | 120 | 0 | 308 |
| keygen | 2 | 120 | 0 | 314 |
| keygen | 3 | 120 | 0 | 251 |
| keygen | 4 | 120 | 0 | 256 |
| decompile | 0 | 120 | 0 | 287 |
| decompile | 1 | 120 | 0 | 288 |
| decompile | 2 | 120 | 0 | 229 |
| decompile | 3 | 120 | 0 | 276.5 |
| decompile | 4 | 120 | 0 | 381 |
| formats | 0 | 120 | 0 | 969 |
| formats | 1 | 120 | 0 | 985 |
| formats | 2 | 120 | 0 | 608 |
| formats | 3 | 120 | 0 | 637 |
| formats | 4 | 120 | 0 | 775 |

Failures count tasks with one or more failed checks. Keygen L0 has no provided binary, so its disassembly count is n/a.

## Failure details

No failures.


## Docker gold/no-op validation

| Family | Level | Split | Tasks | Gold valid | No-op valid |
| --- | ---: | --- | ---: | ---: | ---: |
| keygen | 0 | train | 5 | 5 | 5 |
| keygen | 1 | train | 5 | 5 | 5 |
| keygen | 2 | train | 5 | 5 | 5 |
| keygen | 3 | train | 5 | 5 | 5 |
| keygen | 4 | train | 5 | 5 | 5 |
| keygen | 0 | eval | 3 | 3 | 3 |
| keygen | 4 | eval | 3 | 3 | 3 |
| decompile | 0 | train | 5 | 5 | 5 |
| decompile | 1 | train | 5 | 5 | 5 |
| decompile | 2 | train | 5 | 5 | 5 |
| decompile | 3 | train | 5 | 5 | 5 |
| decompile | 4 | train | 5 | 5 | 5 |
| decompile | 0 | eval | 3 | 3 | 3 |
| decompile | 4 | eval | 3 | 3 | 3 |
| formats | 0 | train | 5 | 5 | 5 |
| formats | 1 | train | 5 | 5 | 5 |
| formats | 2 | train | 5 | 5 | 5 |
| formats | 3 | train | 5 | 5 | 5 |
| formats | 4 | train | 5 | 5 | 5 |
| formats | 0 | eval | 3 | 3 | 3 |
| formats | 4 | eval | 3 | 3 | 3 |

All gold and no-op validations were valid.
