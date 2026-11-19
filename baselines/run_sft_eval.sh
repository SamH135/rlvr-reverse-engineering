#!/bin/sh
# Base vs tuned (Ollama, num_ctx 8192) on EVAL seeds (1_000_000+), per cell, one model at a time.
# Usage: MODELS="qwen3-4b-inst-base re-sft" FAMS="decompile keygen formats" LEVELS="0 1" N=5 sh run_sft_eval.sh
for lvl in ${LEVELS:-0 1}; do for fam in ${FAMS:-decompile keygen formats}; do for m in ${MODELS:-qwen3-4b-inst-base re-sft}; do
  echo "=== $m $fam L$lvl $(date -u +%H:%M:%S)"
  OLLAMA_KEY=ollama uv run vf-run $fam -n ${N:-5} -r 1 -c 1 -m $m \
    --client.base-url http://localhost:11434/v1 --client.api-key-var OLLAMA_KEY \
    --env.agent.runtime.type docker --env.taskset.level $lvl --env.taskset.split eval \
    --env.agent.max-turns 30 2>&1 | grep -E "rollout done|episodes ok|Error" | cut -c1-200
done; done; done
