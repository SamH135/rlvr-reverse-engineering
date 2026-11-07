#!/bin/sh
# Local CPU baseline (Ollama, MODEL default qwen3:1.7b): 3 tasks at L0 per RE family.
for fam in ${@:-keygen decompile formats}; do
  echo "=== $fam L0 $(date -u +%H:%M:%S)"
  OLLAMA_KEY=ollama uv run vf-run $fam -n 3 -r 1 -c 1 -m ${MODEL:-qwen3:1.7b} \
    --client.base-url http://localhost:11434/v1 --client.api-key-var OLLAMA_KEY \
    --env.agent.runtime.type docker --env.taskset.level 0 --env.agent.max-turns 30 2>&1 | grep -E "rollout done|episodes ok|Error" | cut -c1-200
done
