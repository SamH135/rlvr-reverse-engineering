# Status — local-model training & data collection

Updated: 2026-11-21 (evening). Numbers live in `baselines/results_dpo_v1.json`; this file is the "where are we" pointer.

## Headline
`re-dpo` (Qwen3-4B SFT→DPO v1): **decompile L0 3/20, keygen L0 8/20** held-out solves vs SFT-only ~1/12 eval and base 0. First measurable gain.

## Transcript verification (done 11-21)
4 solve transcripts read end-to-end: rewards are real (write → differential-test against oracle → fix → re-verify → done). Residual pathology: **post-solve / mid-task looping to max_turns** — e.g. seed 1000007 solved early, then ran a broken self-check (literal f-string as serial) 34× to the cap. 8/11 solves ended at max_turns. DPO improved *conversion*, not *termination*.

## Model lineage
- `qwen3-4b-inst-base` — base Qwen3-4B-Instruct-2507 Q4_K_M (Ollama, ctx 8192, predict 2048)
- `re-v3c` — SFT LoRA on `sft/train_v2_c.jsonl` (405 rows)
- `re-dpo` — DPO v1 on top of v3c LoRA (69 real + 60 synth pairs, beta 0.1, 1 epoch)

## Data state
- `sft/train_v3.jsonl` — 406 chosen rows (deepseek + swe2 formats + 1 mistral)
- `sft/train_v5.jsonl` — 537 rows = v4 (456) + 42 later swe2 solves + 39 deepseek solves missed by raw build. Audit: all prompts match current taskset, levels <=4, train seeds, <=16k chars, no dup keys; prompt_c suffix appended to the swe2 rows (they were collected without it). Excluded: gemma-26b (messy, redundant post-solve tool calls), deepseek L5/L6 (held out), 31 swe2 rows >16k chars (formats L2/L3), 58 raw rows whose prompts no longer match the current generators.
- `sft/dpo_v1.jsonl` — 81 real pairs (decompile 31, keygen 50)
- `sft/dpo_synth.jsonl` — 121 synthetic early-quit pairs
- swe2 formats collection: ~50 eps, mostly solves at L1–L3 (in train_v3); workers now retargeted at decompile L1–L3 + keygen L1–L2 chosen gaps

## Running
- Nothing. `eval_dpo_v2.log` killed at 12/20 decompile episodes (1 solve, 7 max_turns, 4 provider errors) — partial, inconclusive; keygen cell never ran. Relaunch keygen L0 eval for re-dpo-v2 tomorrow to get the decisive cell.
- swe2 gap-fill workers done (formats L1–L3 + decompile/keygen mid-levels collected).

## Next
1. Relaunch re-dpo-v2 keygen L0 eval (seeds 1M..19, cap 30, prompt_c) — the decisive cell
2. Compare vs v1 (3/20 decompile, 8/20 keygen): if ≤2 decompile + ≤6 keygen → flat/regression → try beta 0.05 or real-only ablation, or treat v1 as the result and move to GRPO/post-solve-loop pairs
3. Open: post-solve-loop rejection pairs need builder changes (solve-then-loop episodes score 1.0, not captured today)

## Gotchas
- Eval seeds ≥1,000,000 never go in training data (builders enforce).
- Provider errors (malformed tool-call JSON, ctx overflow) are serving issues — count separately; DPO doesn't fix them.
- Rejection-harvest runs can use lower max-turns than eval runs — a 20-turn loop is still a loop.
- `baselines/logs/` and `outputs/` are gitignored; results files are the durable record.
