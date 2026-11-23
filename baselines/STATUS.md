# Status — local-model training & data collection

Updated: 2026-11-23. Numbers live in `baselines/results_dpo_v1.json`; this file is the "where are we" pointer.

## Headline
`re-dpo-v5` (SFT v5 → on-policy DPO): **keygen L0 11/20, decompile L0 4–5/20** held-out solves — best raw scoreboard to date (v5 SFT 9+5, DPO v1 8+3). ~70% of solves now stop cleanly (vs 50% v5, 0% v1). max_turns looping unchanged: still the dominant failure mode — on-policy DPO did not kill it.

## Transcript verification (done 11-21)
4 solve transcripts read end-to-end: rewards are real (write → differential-test against oracle → fix → re-verify → done). Residual pathology: **post-solve / mid-task looping to max_turns** — e.g. seed 1000007 solved early, then ran a broken self-check (literal f-string as serial) 34× to the cap. 8/11 solves ended at max_turns. DPO improved *conversion*, not *termination*.

## Model lineage
- `qwen3-4b-inst-base` — base Qwen3-4B-Instruct-2507 Q4_K_M (Ollama, ctx 8192, predict 2048)
- `re-v3c` — SFT LoRA on `sft/train_v2_c.jsonl` (405 rows)
- `re-dpo` — DPO v1 on top of v3c LoRA (69 real + 60 synth pairs, beta 0.1, 1 epoch)
- `re-dpo-v2` — DPO v2 on v3c LoRA (92 real + same 60 synth). keygen L0 3/18 (vs v1 8/20) — regression, closed
- `re-v5` — fresh SFT LoRA on `sft/train_v5.jsonl` (537 rows). keygen L0 9/20, decompile L0 5/20; 7/14 solves stopped cleanly
- `re-dpo-v5` — DPO on v5 LoRA, `sft/dpo_v5.jsonl` (39 on-policy re-v5 rejections + 12 synth), warmup 1, lr 2e-5. **keygen L0 11/20** (6/11 clean stops), **decompile L0 4/20 + 5/20** (two runs, 8/9 clean stops). Best raw score; loops not reduced

## Data state
- `sft/train_v3.jsonl` — 406 chosen rows (deepseek + swe2 formats + 1 mistral)
- `sft/train_v5.jsonl` — 537 rows = v4 (456) + 42 later swe2 solves + 39 deepseek solves missed by raw build. Audit: all prompts match current taskset, levels <=4, train seeds, <=16k chars, no dup keys; prompt_c suffix appended to the swe2 rows (they were collected without it). Excluded: gemma-26b (messy, redundant post-solve tool calls), deepseek L5/L6 (held out), 31 swe2 rows >16k chars (formats L2/L3), 58 raw rows whose prompts no longer match the current generators.
- `sft/dpo_v1.jsonl` — 81 real pairs (decompile 31, keygen 50)
- `sft/dpo_synth.jsonl` — 121 synthetic early-quit pairs
- `tmp_dpo_audit/dpo_v5_candidate.jsonl` — superseded snapshot; was 128 pairs vs re-v5 policy, only 35 on-policy. Rebuilt after chain-2 drained into the two files below.
- `sft/dpo_v5.jsonl` — 51 pairs = 39 on-policy re-v5 rejections (raised `--max-chars` recovered the long loop transcripts) + 12 `dpo_synth` early-quit pairs. **Used for re-dpo-v5.** Do not merge `dpo_synth.jsonl` again — its rows are already inside.
- `sft/dpo_v5_stoploop.jsonl` — 18 solve-then-loop pairs (rejected = episode solved early then looped to cap). Built but NOT trained yet — separate run B; risk: rejected prefix contains a good solve.
- swe2 formats collection: ~50 eps, mostly solves at L1–L3 (in train_v3); workers now retargeted at decompile L1–L3 + keygen L1–L2 chosen gaps

## Running
- `eval_dpo_v2_keygen.log` — killed at 18/20: **3 solves, 7 provider errors** (mixed malformed-args + one ctx overflow), 8 max_turns/other fails. Flat-to-regression vs v1's 8/20; verdict per decision rule: treat v1 as the DPO result.
- `eval_sft_v5_pod.log` — DONE. `re-v5` (SFT on train_v5, 537 rows), Q4_K_M via Ollama 0.40.17 on a rented Runpod RTX 3090 (num_ctx 8192, same Modelfile params as v1/v2), seeds 1M..19, cap 30, prompt_c, n=20/cell. **keygen L0 9/20** (7 max_turns, 4 provider errors); **decompile L0 5/20** (11 max_turns, 4 provider errors). v1 was keygen 8/20 (8 prov. errors), decompile 3/20 (6). 7 of the 14 solves ended with `agent_completed` (model stopped itself); v1 solves all looped to the cap. n=20 so differences of 1-2 solves are noise; the clean-stop behavior is the more notable change. (An earlier local run `eval_sft_v5.log` was invalid: ctx 4096; ignore.)
- `eval_dpo_v2.log` decompile cell was killed at 12/20 (1 solve, 7 max_turns, 4 provider errors) — partial, inconclusive.
- `eval_dpo_v5_pod.log` / `eval_dpo_v5_dec.log` — DONE 2026-11-23, `re-dpo-v5` on Runpod A40 ($0.59/hr; community GPUs all out of stock). Same protocol (eval seeds, L0, n=20, cap 30, prompt_c). **keygen 11/20**: 2 ProviderError, 1 quit, 6 max_turns fails; 6/11 solves clean `agent_completed`, 5 looped to cap. **decompile run A 4/20** (all 4 clean stops ≤5 turns; 12 loops, 2 quits, 1 PE, 1 SandboxError) and **run B 5/20** — the script's duplicate decompile pass accidentally gave a free replication: 8/9 clean stops, ~10 loops, 4 PE incl. 1 ctx-overflow (18777-tok request). Solve overlap across runs: t7/t8/t19 both, t2 only A, t3/t17 only B — temp-0.7 variance flips 2–3 marginal seeds. Pod deleted after run; a `poweroff -f || kill -9 1` dead-man switch failed silently (container couldn't halt → ~4h idle burn ≈ $2.10 — use `delete-pod`/console instead).
- swe2 gap-fill workers done (formats L1–L3 + decompile/keygen mid-levels collected).

## Cost & hardware
- SWE-2 teacher episodes: $0 marginal — included in the existing Devin $20/mo subscription. SWE-2 has no API, so `tools/swe2_proxy.py` + `swe2_worker.py` bridge it via a file queue (that's why the adapter exists).
- DeepSeek/OpenRouter teacher + eval calls: <$20 total to date.
- Training: Colab (Qwen3-4B LoRA via Unsloth, e.g. v5 = 537 rows / 70 steps / 2 epochs ≈ 2h15m).
- Inference + eval loop: local **Quadro T2000 (4GB)**, Q4_K_M via llama-server/Ollama, ctx 8192 — hence 30–60 min episodes and the tool-parse provider errors.
- Total cash outlay beyond the Devin sub: <$20 + **$5.73 Runpod** lifetime (v5 collection pod ~$1.3 + A40 eval pod ~$4.1 incl. ~$2.1 idle burn when the container-side dead-man switch failed — terminate via `delete-pod`, not in-pod poweroff).

## Next
1. ~~DPO-on-re-v5~~ — DONE. Result above: raw score up (11+4/5 vs 9+5), clean-stop rate up (~70% vs 50%), **loop rate unchanged** — single-epoch on-policy DPO moves conversion/termination-on-success, not the loop pathology itself.
2. Decide run B: `sft/dpo_v5_stoploop.jsonl` (18 solve-then-loop pairs) is built and ready. Now the most-targeted lever left — dpo-v5 keygen still had 5/11 solves loop to cap. Same recipe (warmup 1, lr 2e-5) on top of the dpo-v5 adapter, or retrain from re-v5 adapter with both files (69 pairs) — latter is cleaner attribution.
3. Open: GRPO / on-policy RL is the next lever after DPO-on-v5 (DafnyBench-style verifiable-reward gains of +9–25pts at 4B scale per literature). The persisting loop pathology is an argument for on-policy RL with a length/stop bonus, which DPO pairs can't express.

## Gotchas
- Eval seeds ≥1,000,000 never go in training data (builders enforce).
- Provider errors (malformed tool-call JSON, ctx overflow) are serving issues — count separately; DPO doesn't fix them.
- Rejection-harvest runs can use lower max-turns than eval runs — a 20-turn loop is still a loop.
- `baselines/logs/` and `outputs/` are gitignored; results files are the durable record.
