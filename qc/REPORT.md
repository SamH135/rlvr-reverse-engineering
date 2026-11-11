# Multi-seed QC report

Host-side generated-program checks; no Docker runtime or model was used.
Train seeds: 0–99; eval seeds: 1,000,000–1,000,019. Each family/level cell covers 120 tasks.
Sweep runtime: 2m 16.9s (136.9s).

| Family | Level | Tasks checked | Failed tasks | Median `objdump -d` lines |
| --- | ---: | ---: | ---: | ---: |
| keygen | 0 | 120 | 0 | n/a |
| keygen | 1 | 120 | 0 | 267 |
| keygen | 2 | 120 | 0 | 273 |
| keygen | 3 | 120 | 0 | 218 |
| keygen | 4 | 120 | 0 | 217 |
| decompile | 0 | 120 | 0 | 244 |
| decompile | 1 | 120 | 0 | 244 |
| decompile | 2 | 120 | 0 | 215 |
| decompile | 3 | 120 | 0 | 257 |
| decompile | 4 | 120 | 0 | 357 |
| formats | 0 | 120 | 0 | 879 |
| formats | 1 | 120 | 0 | 895 |
| formats | 2 | 120 | 0 | 511 |
| formats | 3 | 120 | 0 | 574.5 |
| formats | 4 | 120 | 0 | 728.5 |

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
| keygen | 5 | train | 5 | 5 | 5 |
| keygen | 6 | train | 5 | 5 | 5 |
| keygen | 0 | eval | 3 | 3 | 3 |
| keygen | 4 | eval | 3 | 3 | 3 |
| decompile | 0 | train | 5 | 5 | 5 |
| decompile | 1 | train | 5 | 5 | 5 |
| decompile | 2 | train | 5 | 5 | 5 |
| decompile | 3 | train | 5 | 5 | 5 |
| decompile | 4 | train | 5 | 5 | 5 |
| decompile | 5 | train | 5 | 5 | 5 |
| decompile | 6 | train | 5 | 5 | 5 |
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
