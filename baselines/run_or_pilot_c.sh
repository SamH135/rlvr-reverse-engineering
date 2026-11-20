#!/bin/sh
# Sequential OpenRouter pilot under prompt arm C. Usage: FAM=keygen N=3 MODELS="a/b c/d" sh run_or_pilot_c.sh
for m in $MODELS; do echo "=== $m ${FAM:-keygen} $(date +%H:%M:%S)"; MODE=or MODEL=$m N=${N:-3} FAM=${FAM:-keygen} sh baselines/run_prompt_c.sh; done
