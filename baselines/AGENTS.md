# baselines: model runs and recorded results

- `run_gemini_re.sh`: env `OUT_DIR` (default `baselines/logs`), `N` (default 3), `LITELLM_KEY` (required). Levels 0/2/4 for keygen, decompile, formats via a LiteLLM proxy at `localhost:4000`. Aborts if all `N` episodes are provider errors.
- `run_qwen_re.sh`: Ollama at `localhost:11434`, L0 only, `MODEL` default `qwen3:1.7b`.
- `results.json`: hand-recorded results and provider notes, not script output. `logs/` is gitignored.
- `view_trace.py`: prints readable episode transcripts from `outputs/*/traces.jsonl` (commands, tool output, verdict line). `-i N` picks one episode; `--full`, `--reasoning` widen output.
- `summarize.py`: aggregates episodes into solved/completed/attempted/provider- and harness-error counts plus tokens and ~cost. Counting definitions live in its docstring; edit `PRICES` before quoting costs.

## Gotchas
- Gemini (`gemini-3.1-flash-lite`) crashes on streaming tool calls directly, so use LiteLLM (`PYTHONUTF8=1` on Windows); free tier is 15 requests/min. DeepSeek (`deepseek-flash`) works without a proxy.
- Keys are in `src/.env` (gitignored). Never print, log or commit them; they were exposed earlier and should be rotated.
- Provider errors score 0 in the harness but are not agent failures: report attempted, completed, solved and provider-error counts separately.
- Groq (2026-11): llama-3.3-70b-versatile and llama-3.1-8b-instant are retired; /models needs a browser-like `User-Agent` (pass via `--client.headers '{"User-Agent":"Mozilla/5.0"}'`). gpt-oss-* models fail: Groq's endpoint rejects the harmony `channel` field on replayed assistant messages. Free tier is tiny (ITPM 7k, OTPM 1k tokens/min per model) — sweeps need paid tier.
- Ollama must be running with the model pulled (`curl localhost:11434/api/tags`); it was absent on 2026-11-11.
- Ollama recipe: `winget install Ollama.Ollama`; kill the auto-started tray (`taskkill` the `ollama app.exe`/`ollama.exe` PIDs), then `OLLAMA_CONTEXT_LENGTH=16384 ollama serve` — default num_ctx 4096 truncates agent transcripts. `ollama cp qwen3:1.7b qwen3-1p7b` because `:` in model names breaks Windows output dirs (`OSError WinError 123`). Tool calls work on the /v1 endpoint; CPU-bound ~2-6 min/episode at L0-L2, but a single max-turns formats episode can run hours — cap N and watch wall time.
- Weak models need the pre-created stub deliverable (0.3+): `edit` cannot create files, so an absent deliverable = guaranteed scope fail (tool friction, not capability).
- Finding: a cheap model solved 39/39 at L0/L2/L4. Root cause found 2026-11-09: ~half of decompile seeds generated constant functions (no fold stage) and keygen allowed adjacent `table` ops that cancel — both fixed (generators now re-roll/avoid name-independent output). Re-run baselines before treating levels as saturated. Cost figures are estimates, not aggregated from logs.

## Testing
No tests; these are manual, costly runs. Do not launch them unprompted. Shell edits: `sh -n <file>`.
