# tools: dev utilities

Transcript viewer: `view_transcripts.py`. Data builders: `build_sft.py`
(`--glob` selects the trace dirs; default is deepseek teacher runs),
`build_dpo.py`, `find_recovery.py`, `rewrite_sft_prompts.py`, `synth_dpo.py`,
`synth_recovery.py`, `watch_runs.py`, `truncate_stop.py` (replays keygen L0
solve-then-loop episodes in Docker, cuts after the first verified-solve +
verification turn, appends a clean-stop "done" message; needs
`rlvr-keygen:0.2`), `build_stop_pairs.py` (same replay, but emits prefix-shared
DPO pairs at every verified still-passing turn before the next tool call —
chosen = stop text, rejected = the actual next tool-call turn; cap 3/episode).
`dpo_train.py` is the notebook's DPO recipe as a
script for rented GPUs (Colab T4 OOMs on run B): `python dpo_train.py <adapter> <pairs.jsonl> <out>`.

## swe2_*: Devin/SWE-2 as an in-env teacher policy

`swe2_proxy.py` is a stdlib-only OpenAI-compatible relay: `vf-run` posts
`chat.completions` to it, each request becomes a file in a queue dir, and a
worker (Devin or a subagent) answers it via `swe2_worker.py`. The harness,
sandbox, tools, and grading all run for real and vf-run emits native traces —
the only thing replaced is the upstream model.

```sh
# One worker session == one run. Do NOT share a queue across sessions.
UV="py -m uv" FAM=formats LEVEL=1 N=8 C=2 OFFSET=766 sh tools/swe2_run.sh
# -> prints "[swe2] run owns port=NNNNN queue=tmp_swe2/qNNNNN"; then loop:
py tools/swe2_worker.py --queue tmp_swe2/qNNNNN claim --wait 3600
py tools/swe2_worker.py --queue tmp_swe2/qNNNNN respond <key> --say "..." --bash "..."
```

- `swe2_run.sh` picks a free `PORT` when unset and derives the queue
  `tmp_swe2/q<port>` — two sessions can never collide (Windows silently
  double-binds reused ports and splits traffic between queues; don't set PORT).
  Each run prints its own claim command.

- Queue: `tmp_swe2/q<port>/{pending,claimed,responses}` (gitignored). Request
  key = sha256(model+tools+messages) — retries collapse onto one pending item
  and identical requests get identical answers (keep `-r 1`, distinct seeds).
- Responses SSE-stream and **must close the connection** after `[DONE]`: the
  interception layer serializes a rollout's upstream calls, so an unbounded
  response deadlocks the episode (learned the hard way: `ProviderError`).
- Worker contract: a turn is tool calls (`--bash`, `--tool-call`, or `--file`
  with `{"content","tool_calls"}`) or plain text (`--say`, no calls = episode
  end). `claim --wait` exits 3 on queue STOP/timeout — loop it in subagents.
- Constraints: agent httpx read timeout 600s/request (heartbeats hold it);
  ~3 retries before the episode dies as provider error. Answer promptly.
- Traces land in `outputs/<fam>--swe2--bash--*/`; SFT conversion:
  `tools/build_sft.py --glob "outputs/*--swe2--*/traces.jsonl"`.
- Honesty rule for workers: solve from the request messages only. Do not open
  generator/taskset source while answering a queue turn — the point is
  reproducible agent behavior, not oracle answers. Train seeds < 1,000,000.

Known gap: usage/token fields are zeroed; `summarize.py` cost numbers are
meaningless on swe2 runs.
