#!/bin/sh
# Kill vf-* sandbox containers older than MAX_MIN minutes (default 15): a model-launched runaway command
# wedges the episode, and vf-run has no per-command timeout. Healthy episodes finish in 1-5 minutes.
# The killed episode logs HarnessError/SandboxError, which tools/build_dpo.py excludes.
# Usage: sh tools/eval_watchdog.sh   (leave running next to vf-run; Ctrl-C to stop)
MAX=${MAX_MIN:-15}
while true; do
  for c in $(docker ps -q --filter name=vf-); do
    s=$(docker inspect -f '{{.State.StartedAt}}' "$c" 2>/dev/null) || continue
    [ -n "$s" ] || continue
    age=$(( ($(date +%s) - $(date -d "$s" +%s)) / 60 ))
    [ "$age" -ge "$MAX" ] && { echo "$(date +%T) killing $c age=${age}m"; docker kill "$c" >/dev/null; }
  done
  sleep 30
done
