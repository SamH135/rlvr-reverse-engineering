#!/bin/sh
# Prompt arm C: 0.3.5 task prompt + workflow system prompt (baselines/prompt_c.txt). Usage: MODE=local|or MODEL=... N=5 sh run_prompt_c.sh
if [ "$MODE" = "or" ]; then
  set -a; . src/.env; set +a
  uv run vf-run ${FAM:-decompile} -n ${N:-3} -r 1 -c 1 -m $MODEL --client.base-url https://openrouter.ai/api/v1 --client.api-key-var OPENROUTER_API_KEY \
    --env.agent.runtime.type docker --env.taskset.level ${LEVEL:-0} --env.taskset.seed-offset ${OFFSET:-100} --env.agent.max-turns 30 --env.taskset.system-prompt baselines/prompt_c.txt 2>&1 | grep --line-buffered -E "rollout done|episodes ok|Error" | stdbuf -oL cut -c1-200
else
  OLLAMA_KEY=ollama uv run vf-run ${FAM:-decompile} -n ${N:-5} -r 1 -c 1 -m $MODEL --client.base-url http://localhost:11434/v1 --client.api-key-var OLLAMA_KEY \
    --env.agent.runtime.type docker --env.taskset.level 0 --env.taskset.split eval --env.agent.max-turns 30 --env.taskset.system-prompt baselines/prompt_c.txt 2>&1 | grep --line-buffered -E "rollout done|episodes ok|Error" | stdbuf -oL cut -c1-200
fi
