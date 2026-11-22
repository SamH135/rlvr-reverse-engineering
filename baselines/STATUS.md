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
- `sft/dpo_v1.jsonl` — 81 real pairs (decompile 31, keygen 50)
- `sft/dpo_synth.jsonl` — 121 synthetic early-quit pairs
- swe2 formats collection: ~50 eps, mostly solves at L1–L3 (in train_v3); workers now retargeted at decompile L1–L3 + keygen L1–L2 chosen gaps

## Running
- `collect_dpo_v2c.log` — re-dpo on decompile L0 train seeds 24–39, **max_turns 20** (rejection harvest only; chosen already exists on these seeds). Expect ~12–16 on-policy rejections overnight.
- swe2 gap-fill workers done for now (formats L1–L3 collected); orchestration: `tools/swe2_run.sh` + `swe2_worker.py`, per-session queue `tmp_swe2/q<port>`.

## Next (DPO v2 pre-flight)
1. Collection done → rebuild dpo (`tools/build_dpo.py`; expect ~95–105 pairs incl. ~15 on-policy)
2. Spot-check new rejected endings
3. Colab DPO v2: same recipe as v1 (beta 0.1, 1 epoch, lr 5e-5, 60-synth mix) for comparability
4. Eval identical cells → compare vs results_dpo_v1.json
5. Open: real-only ablation; L1 eval cells; post-solve-loop pairs need builder changes (solve-then-loop episodes score 1.0, not captured as rejections today)

## Gotchas
- Eval seeds ≥1,000,000 never go in training data (builders enforce).
- Provider errors (malformed tool-call JSON, ctx overflow) are serving issues — count separately; DPO doesn't fix them.
- Rejection-harvest runs can use lower max-turns than eval runs — a 20-turn loop is still a loop.
- `baselines/logs/` and `outputs/` are gitignored; results files are the durable record.
