#!/bin/sh
# Teacher rollouts (deepseek-flash, default access, train seeds 10..) for SFT. Usage: LEVELS="0 1 2 3" N=25 sh gen_sft_data.sh
set -a; . src/.env; set +a
for lvl in ${LEVELS:-0 1 2 3}; do for fam in ${FAMS:-decompile keygen formats}; do
  echo "=== $fam L$lvl $(date -u +%H:%M:%S)"
  uv run vf-run $fam -n ${N:-25} -r 1 -c ${C:-4} -m deepseek-flash \
    --client.base-url https://api.deepseek.com --client.api-key-var DEEPSEEK_API_KEY \
    --env.agent.runtime.type docker --env.taskset.level $lvl --env.taskset.seed-offset ${OFFSET:-10} \
    --env.agent.max-turns 30 2>&1 | grep -E "episodes ok|Error" | stdbuf -oL cut -c1-200
done; done
