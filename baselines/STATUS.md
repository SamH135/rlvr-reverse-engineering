# Status — local-model training & data collection

Updated: 2026-11-22. Numbers live in `baselines/results_dpo_v1.json`; this file is the "where are we" pointer.

## Headline
`re-dpo` (Qwen3-4B SFT→DPO v1): **decompile L0 3/20, keygen L0 8/20** held-out solves vs SFT-only ~1/12 eval and base 0. First measurable gain.

## Transcript verification (done 11-21)
4 solve transcripts read end-to-end: rewards are real (write → differential-test against oracle → fix → re-verify → done). Residual pathology: **post-solve / mid-task looping to max_turns** — e.g. seed 1000007 solved early, then ran a broken self-check (literal f-string as serial) 34× to the cap. 8/11 solves ended at max_turns. DPO improved *conversion*, not *termination*.

## Model lineage
- `qwen3-4b-inst-base` — base Qwen3-4B-Instruct-2507 Q4_K_M (Ollama, ctx 8192, predict 2048)
- `re-v3c` — SFT LoRA on `sft/train_v2_c.jsonl` (405 rows)
- `re-dpo` — DPO v1 on top of v3c LoRA (69 real + 60 synth pairs, beta 0.1, 1 epoch)
- `re-dpo-v2` — DPO v2 on v3c LoRA (92 real + same 60 synth). keygen L0 3/18 (vs v1 8/20) — regression, closed
- `re-v5` — fresh SFT LoRA on `sft/train_v5.jsonl` (537 rows). keygen L0 9/20, decompile L0 5/20; 7/14 solves stopped cleanly

## Data state
- `sft/train_v3.jsonl` — 406 chosen rows (deepseek + swe2 formats + 1 mistral)
- `sft/train_v5.jsonl` — 537 rows = v4 (456) + 42 later swe2 solves + 39 deepseek solves missed by raw build. Audit: all prompts match current taskset, levels <=4, train seeds, <=16k chars, no dup keys; prompt_c suffix appended to the swe2 rows (they were collected without it). Excluded: gemma-26b (messy, redundant post-solve tool calls), deepseek L5/L6 (held out), 31 swe2 rows >16k chars (formats L2/L3), 58 raw rows whose prompts no longer match the current generators.
- `sft/dpo_v1.jsonl` — 81 real pairs (decompile 31, keygen 50)
- `sft/dpo_synth.jsonl` — 121 synthetic early-quit pairs
- `tmp_dpo_audit/dpo_v5_candidate.jsonl` — 128 pairs vs re-v5 policy, only 35 on-policy (re-v5 rejections: 22 decompile-L0, 13 keygen-L0); 93 stale off-policy — do NOT train on the full file. Rebuild via `tools/build_dpo.py sft/train_v5.jsonl` after chain-2 drains; raise `--max-chars` so the 9 dropped re-v5 loop transcripts survive. 9 candidates had seeds with no pair (decompile s0, keygen s5/s31) and 6 fell back to stale rejections purely from length.
- swe2 formats collection: ~50 eps, mostly solves at L1–L3 (in train_v3); workers now retargeted at decompile L1–L3 + keygen L1–L2 chosen gaps

## Running
- `eval_dpo_v2_keygen.log` — killed at 18/20: **3 solves, 7 provider errors** (mixed malformed-args + one ctx overflow), 8 max_turns/other fails. Flat-to-regression vs v1's 8/20; verdict per decision rule: treat v1 as the DPO result.
- `eval_sft_v5_pod.log` — DONE. `re-v5` (SFT on train_v5, 537 rows), Q4_K_M via Ollama 0.40.17 on a rented Runpod RTX 3090 (num_ctx 8192, same Modelfile params as v1/v2), seeds 1M..19, cap 30, prompt_c, n=20/cell. **keygen L0 9/20** (7 max_turns, 4 provider errors); **decompile L0 5/20** (11 max_turns, 4 provider errors). v1 was keygen 8/20 (8 prov. errors), decompile 3/20 (6). 7 of the 14 solves ended with `agent_completed` (model stopped itself); v1 solves all looped to the cap. n=20 so differences of 1-2 solves are noise; the clean-stop behavior is the more notable change. (An earlier local run `eval_sft_v5.log` was invalid: ctx 4096; ignore.)
- `eval_dpo_v2.log` decompile cell was killed at 12/20 (1 solve, 7 max_turns, 4 provider errors) — partial, inconclusive.
- swe2 gap-fill workers done (formats L1–L3 + decompile/keygen mid-levels collected).

## Cost & hardware
- SWE-2 teacher episodes: $0 marginal — included in the existing Devin $20/mo subscription. SWE-2 has no API, so `tools/swe2_proxy.py` + `swe2_worker.py` bridge it via a file queue (that's why the adapter exists).
- DeepSeek/OpenRouter teacher + eval calls: <$20 total to date.
- Training: Colab (Qwen3-4B LoRA via Unsloth, e.g. v5 = 537 rows / 70 steps / 2 epochs ≈ 2h15m).
- Inference + eval loop: local **Quadro T2000 (4GB)**, Q4_K_M via llama-server/Ollama, ctx 8192 — hence 30–60 min episodes and the tool-parse provider errors.
- Total cash outlay beyond the Devin sub: <$20.

## Next
1. DPO-on-re-v5 — audit verdict GO, on-policy slice only:
   a. Wait for `v5_collect2` chain-2 to drain (keygen eval ext. ~task 35/40 at last check)
   b. Rebuild `dpo_v5.jsonl` with raised `--max-chars`; keep only `rejected_from` == re-v5 rows (~40 expected) + 10–15 `dpo_synth` early-quit pairs
   c. Config fixes vs v1/v2 recipe: `warmup_steps=1` (45 pairs ≈ 6 optimizer steps — warmup 5 ≈ the whole run) and consider lr 2e-5 (v1/v2 margins exploded by step 7)
   d. Success metric = fewer loops/quits among failures, not solve-count delta (n=20 noise band is ±3 solves)
2. Follow-up data (separate run): ~18 solve-then-loop pairs — re-v5 has 27 solved-to-cap episodes invisible to the builder (score 1.0). Chosen=teacher clean-stop trace, rejected=loop tail truncated to the post-solve turns. Needs builder changes; risk flagged: rejected prefix contains a good solve.
3. Open: GRPO / on-policy RL is the next lever after DPO-on-v5 (DafnyBench-style verifiable-reward gains of +9–25pts at 4B scale per literature).

## Gotchas
- Eval seeds ≥1,000,000 never go in training data (builders enforce).
- Provider errors (malformed tool-call JSON, ctx overflow) are serving issues — count separately; DPO doesn't fix them.
- Rejection-harvest runs can use lower max-turns than eval runs — a 20-turn loop is still a loop.
- `baselines/logs/` and `outputs/` are gitignored; results files are the durable record.
