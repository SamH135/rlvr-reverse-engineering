#!/bin/sh
# Gemini Flash-Lite baseline: 3 tasks x levels 0/2/4 per RE family, sequential.
# Provider-error episodes are excluded later; abort only if a whole run is provider errors (quota gone).
# Usage: run_gemini_re.sh [skip...]   e.g. run_gemini_re.sh keygen:0
OUT_DIR=${OUT_DIR:-baselines/logs}
N=${N:-3}
: "${LITELLM_KEY:?set LITELLM_KEY}"
mkdir -p "$OUT_DIR"
for fam in keygen decompile formats; do
  for lvl in 0 2 4; do
    case " $* " in *" $fam:$lvl "*) continue;; esac
    echo "=== $fam L$lvl $(date -u +%H:%M:%S)"
    LITELLM_KEY=$LITELLM_KEY uv run vf-run $fam -n $N -r 1 -c 1 -m gemini-flash-lite \
      --client.base-url http://localhost:4000/v1 --client.api-key-var LITELLM_KEY \
      --env.agent.runtime.type docker --env.taskset.level $lvl --env.agent.max-turns 30 > "$OUT_DIR/gem_run.log" 2>&1
    grep -E "rollout done|episodes ok" "$OUT_DIR/gem_run.log" | cut -c1-200
    if [ "$(grep -c "stop=ProviderError" "$OUT_DIR/gem_run.log")" -ge "$N" ]; then echo "ABORT: all provider errors"; exit 1; fi
    cp "$OUT_DIR/gem_run.log" "$OUT_DIR/gemini_logs_${fam}_L${lvl}.log"
  done
done
