#!/bin/sh
# Pilot: base vs tuned (Ollama) on eval seeds, one model at a time. Usage: MODELS="a b" FAM=decompile LEVEL=0 N=3 sh run_sft_pilot.sh
for m in ${MODELS:-qwen3-4b-inst-base re-sft}; do
  echo "=== $m ${FAM:-decompile} L${LEVEL:-0} $(date -u +%H:%M:%S)"
  OLLAMA_KEY=ollama uv run vf-run ${FAM:-decompile} -n ${N:-3} -r 1 -c 1 -m $m \
    --client.base-url http://localhost:11434/v1 --client.api-key-var OLLAMA_KEY \
    --env.agent.runtime.type docker --env.taskset.level ${LEVEL:-0} --env.taskset.split eval \
    --env.agent.max-turns 30 2>&1 | grep -E "rollout done|episodes ok|Error" | stdbuf -oL cut -c1-200
done
