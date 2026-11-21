#!/bin/sh
# OpenRouter candidate-teacher pilot on train seeds. Usage: MODELS="a/b c/d" FAM=decompile LEVEL=0 N=3 sh run_or_pilot.sh
set -a; . src/.env; set +a
for m in ${MODELS}; do
  echo "=== $m ${FAM:-decompile} L${LEVEL:-0} $(date -u +%H:%M:%S)"
  uv run vf-run ${FAM:-decompile} -n ${N:-3} -r 1 -c ${C:-3} -m $m \
    --client.base-url https://openrouter.ai/api/v1 --client.api-key-var OPENROUTER_API_KEY \
    --env.agent.runtime.type docker --env.taskset.level ${LEVEL:-0} --env.taskset.seed-offset ${OFFSET:-100} \
    --env.agent.max-turns 30 2>&1 | grep -E "rollout done|episodes ok|Error" | stdbuf -oL cut -c1-200
done
