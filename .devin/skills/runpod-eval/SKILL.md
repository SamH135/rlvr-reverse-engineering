---
name: runpod-eval
description: Rent a Runpod GPU pod, serve a GGUF model with Ollama, tunnel it to the local vf-run harness, and run the keygen/decompile/formats eval or train-seed data collection. Use when the user wants faster evals than the local 4GB Quadro T2000 allows, or mentions Runpod, a rented GPU, or the pod.
---

# Runpod eval runs (re-v5 workflow)

Verified end to end on 2026-11-22. Only model serving moves to the pod. `vf-run`, the Docker sandboxes, grading and logs stay on the user's Windows PC. The harness talks to any OpenAI-compatible URL, so the only change vs a local run is `--client.base-url`.

Why: local T2000 (4GB) runs a 4B Q4 model at ~45%/55% CPU/GPU, 10-60 min per episode. A rented 3090 is 100% GPU, ~1-2 min per episode. A 40-episode sweep costs ~$0.50.

## One-time setup (already done on this machine; verify, don't redo)
- Runpod MCP: `devin mcp add -s user runpod https://mcp.runpod.io/` then OAuth sign-in (`devin mcp login runpod`). The devin binary is at `C:/Users/samue/AppData/Local/Programs/Devin/resources/app/extensions/windsurf/devin/bin/devin.exe` (not on PATH in bash).
- Account is PREPAID (check with MCP `get-balance`). The user adds credit in the console; never ask for card details.
- User's public key `~/.ssh/id_ed25519.pub` is registered via MCP `update-ssh-keys` (it REPLACES all keys, so read `get-ssh-keys` first).
- Always call `mcp_list_tools` on server `runpod` before `mcp_call_tool`, and read guide `runpod-mcp` once per session (`read-guide`).
- The official skills installer needs Node >= 22.20; the user has v21.1, so skills are skipped. The MCP serves the same playbooks via `read-guide`.

## MCP tool quirks (argument shapes that bit us)
- `get-pod`, `delete-pod`: arg is `id` (not `podId`).
- `pod-action`: `{"id": "...", "body": {"action": "restart"}}`.
- `create-pod` and `update-ssh-keys` take a `body` object. Call `describe-tool` for `create-pod` first.
- `list-gpu-types` needs `include:["AVAILABILITY"]` together with `product:["POD"]`; `cloud` is `COMMUNITY` or `SECURE`.
- `list-public-templates` takes only `source` (official/verified/community).
- Image comes from a session read: template `runpod-torch-v280` (runpod/pytorch:1.0.2-cu1281-torch280-ubuntu2404).

## Pod recipe
State the hourly price to the user BEFORE creating anything billable, and wait for a go.
1. GPU choice used: RTX 3090 community, $0.22/hr (24GB is plenty for a 4B Q4). Fallbacks seen: A40 secure $0.59 (high stock), RTX 4090 secure $0.89. Community 4090 had no stock.
2. `create-pod` body: `{"name":..., "cloud":"COMMUNITY", "templateId":"runpod-torch-v280", "gpu":{"id":"NVIDIA GeForce RTX 3090","count":1,"minCudaVersion":"12.8"}, "ports":["22/tcp"], "startSsh":true, "startJupyter":false, "mounts":{"persistent":{"size":20,"path":"/workspace"}}}`.
3. Poll `get-pod` until `ssh.direct` appears (a few minutes). Use `ssh -o BatchMode=yes -i ~/.ssh/id_ed25519 -p <port> root@<ip>`. Direct SSH supports scp; the proxy (`ssh.runpod.io`) does not. The SSH port CHANGES on every restart; re-read `get-pod`.
4. **Test CUDA before uploading anything:** `python3 -c "import torch; torch.zeros(1).cuda()"`. One community host failed with `cuInit 999` (nvidia-smi worked, PyTorch and Ollama both failed). A restart did not fix it. Delete that pod and create another (a different host appears).
5. Upload (~2.5GB, 5-8 min): `scp -P <port> re-v5.gguf re-v5.Modelfile root@<ip>:/workspace/` from `C:/Users/samue/Downloads`. Verify the byte count matches (2497280416 for re-v5). `/workspace` is host-local and survives `restart` but not `delete`.
6. Install Ollama on the pod: first `apt-get install -y pciutils lshw` (without lspci the installer skips GPU libs), then `curl -fsSL https://ollama.com/install.sh | sh`. Look for "NVIDIA GPU installed". No systemd: start with `OLLAMA_KEEP_ALIVE=24h nohup ollama serve > /workspace/ollama.log 2>&1 &`. Confirm `grep "inference compute" /workspace/ollama.log` shows CUDA/RTX 3090, not `library=cpu`. Pod Ollama was 0.40.17, the same as the user's local one.
7. Register: `sed -i 's#^FROM .*#FROM /workspace/re-v5.gguf#' re-v5.Modelfile && ollama create re-v5 -f re-v5.Modelfile`. Smoke test `/api/generate`. `ollama ps` must show `100% GPU` and context `8192`; model ID `9cc243cf8d82` matches the local copy.

## CRITICAL: the Modelfile must carry the full parameters
A bare `FROM` Modelfile silently drops `num_ctx 8192`, `num_predict 2048`, temperature 0.7, top_k 20, top_p 0.8, repeat_penalty 1 and the `<|im_start|>`/`<|im_end|>` stops. The model then loads at ctx 4096 and the eval is NOT comparable to v1/v2. Build it from an existing model: `ollama show re-dpo-v2 --modelfile`, swap the `FROM` line. Always check `ollama ps` shows 8192 before launching.

## Tunnel and eval launch
- Tunnel: `ssh -N -L 11435:localhost:11434 -o ServerAliveInterval=15 -o ServerAliveCountMax=4 -o ExitOnForwardFailure=yes -i ~/.ssh/id_ed25519 -p <port> root@<ip>`, run as a background exec. Use local port 11435 so the user's local Ollama on 11434 is untouched. Verify with `curl localhost:11435/api/ps`.
- Stop any local eval first: kill the loop shell, then `taskkill //F //T //PID <uv.exe pid>`, then `docker ps -q | xargs -r docker kill`, then `ollama stop <model>`.
- Eval command (run per family, background): `OLLAMA_KEY=ollama py -m uv run vf-run <family> -n 20 -r 1 -c 1 -m re-v5 --client.base-url http://localhost:11435/v1 --client.api-key-var OLLAMA_KEY --env.agent.runtime.type docker --env.taskset.level 0 --env.taskset.split eval --env.agent.max-turns 30 --env.taskset.system-prompt baselines/prompt_c.txt 2>&1 | grep --line-buffered -E "rollout done|episodes ok|Error" | stdbuf -oL cut -c1-200 >> baselines/logs/<name>.log`. Without `stdbuf -oL` the log stays empty until the end.
- Same protocol as v1/v2: eval seeds 1,000,000+, L0, n=20, cap 30, prompt_c. Never change these when comparing models.

## Polling (what worked)
- Log: strip ANSI (`sed 's/\x1b\[[0-9;]*m//g'`) and grep `rollout done`.
- Ground truth is `outputs/<family>--<model>--bash--<run>/traces.jsonl`. Per line: `json.loads(line)["traces"][0]`; solved = `t["rewards"]["solved"]["score"] == 1.0`; else `t["stop_condition"]`. Use `Path(p).parent.name` (Windows backslashes break `split("/")`).
- Report solved count and provider errors separately; `WARNING model call failed` lines are retries, only `stop=ProviderError` loses an episode. A run dir with 0 episodes is an aborted launch; ignore it.
- Stall check: if the log is silent for minutes, run `docker top <vf-container>`. A model-launched runaway command (e.g. `for _ in range(1000000)` spawning subprocesses) once blocked the single-threaded eval for ~42 min. The harness has no per-command timeout that I could find. `docker top` PIDs are host-side; to kill, match by command line inside the container (`docker exec <c> pkill -9 -f ...`). Disclose any manual kill, since it changes that episode.

- Wedged episode (2026-11-22): after the model's runaway command finished, the episode never resumed (GPU 0%, no new request in Ollama log for 13+ min, run dir empty). `docker kill <the one vf-* container>` fixes it: that episode and the next log `stop=HarnessError` (excluded by build_dpo INFRA) and the run continues with the next seed. Re-run the lost seeds afterwards.
- `-n` is capped by the taskset's `num_tasks` (default 20): `-n 50` silently runs 20. Also pass `--env.taskset.num-tasks N` (and set `-n N`) for more than 20 episodes per run.
- Train-seed collection flags: `--env.taskset.split train --env.taskset.seed-offset <n>` (seeds = offset..offset+n-1). Eval extension: `--env.taskset.split eval --env.taskset.seed-offset 20` covers seeds 1,000,020+. L0 solved teacher rows in `sft/train_v5.jsonl`: keygen seeds 0-38, decompile seeds 0-49 (plus a few high seeds).

## Teardown (do not skip, billing is per second)
`delete-pod` with `id` for pods THIS session created, kill the tunnel shell, confirm `list-pods` is empty. Only terminate pods you created or the user named. If the session may end first, tell the user to delete the pod in the console.

## Cost log (2026-11-22)
Pod 1 (bad host, ~15 min) + pod 2 (~2h) at $0.22/hr: about $0.50 of the user's $10 balance. Cost framing: SWE-2 sessions are free under the user's Devin subscription, DeepSeek/OpenRouter spend < $20, training on Colab, local inference on a Quadro T2000 4GB.

## Results to date (keygen L0, eval seeds, n=20)
re-dpo v1 8/20 (8 provider errors); re-dpo-v2 3/18 (7); re-v5 SFT 9/20 (4 provider errors, 5 of 9 solves ended with `agent_completed` instead of looping to the cap). Decompile L0: v1 3/20 (6 errors); re-v5 5/20 (11 max_turns, 4 provider errors, 2 of 5 solves clean-stopped). See `baselines/STATUS.md` for the current table.

## Planned next step: train-seed data for DPO on v5
`tools/build_dpo.py` makes same-seed pairs (chosen = solved teacher row, rejected = failed student attempt on the SAME train seed below 1,000,000). Add `"re-v5"` to its `STUDENT` tuple. Run v5 on train seeds that have solved rows in `sft/train_v5.jsonl`; never use eval-seed failures (contaminates the held-out set). Confirm the exact train-split flag for `vf-run` before launching. v5 was trained on those seeds, so expect fewer failures and a smaller pair pool.
