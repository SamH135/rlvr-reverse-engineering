#!/bin/sh
# Base vs tuned (Ollama, num_ctx 8192, num_predict 1024) on EVAL seeds (1_000_000+), per cell, one model at a time.
# Usage: MODELS="qwen3-4b-inst-base re-sft" FAMS="decompile keygen formats" LEVELS="0 1" N=5 [SP=baselines/prompt_c.txt] sh run_sft_eval.sh
SPARG=""; [ -n "$SP" ] && SPARG="--env.taskset.system-prompt $SP"
for lvl in ${LEVELS:-0 1}; do for fam in ${FAMS:-decompile keygen formats}; do for m in ${MODELS:-qwen3-4b-inst-base re-sft}; do
  echo "=== $m $fam L$lvl ${SP:+(sys=$SP) }$(date -u +%H:%M:%S)"
  OLLAMA_KEY=ollama uv run vf-run $fam -n ${N:-5} -r 1 -c 1 -m $m \
    --client.base-url http://localhost:11434/v1 --client.api-key-var OLLAMA_KEY \
    --env.agent.runtime.type docker --env.taskset.level $lvl --env.taskset.split eval \
    --env.agent.max-turns 30 $SPARG 2>&1 | grep --line-buffered -E "rollout done|episodes ok|Error" | stdbuf -oL cut -c1-200
done; done; done
