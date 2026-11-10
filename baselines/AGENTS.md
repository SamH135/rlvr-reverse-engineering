# baselines: model runs and recorded results

- `run_gemini_re.sh`: env `OUT_DIR` (default `baselines/logs`), `N` (default 3), `LITELLM_KEY` (required). Levels 0/2/4 for keygen, decompile, formats via a LiteLLM proxy at `localhost:4000`. Aborts if all `N` episodes are provider errors.
- `run_qwen_re.sh`: Ollama at `localhost:11434`, L0 only, `MODEL` default `qwen3:1.7b`.
- `results.json`: hand-recorded results and provider notes, not script output. `logs/` is gitignored.

## Gotchas
- Gemini (`gemini-3.1-flash-lite`) crashes on streaming tool calls directly, so use LiteLLM (`PYTHONUTF8=1` on Windows); free tier is 15 requests/min. DeepSeek (`deepseek-flash`) works without a proxy.
- Keys are in `src/.env` (gitignored). Never print, log or commit them; they were exposed earlier and should be rotated.
- Provider errors score 0 in the harness but are not agent failures: report attempted, completed, solved and provider-error counts separately.
- Finding: a cheap model solved 39/39 at L0/L2/L4, so levels do not separate models yet. Cost figures are estimates, not aggregated from logs.

## Testing
No tests; these are manual, costly runs. Do not launch them unprompted. Shell edits: `sh -n <file>`.
