#!/bin/sh
# OpenRouter teacher pass under prompt arm C. Usage: MODEL=google/gemma-4-26b-a4b-it N=15 OFFSET=100 sh gen_or_teacher.sh
for lvl in ${LEVELS:-0 1 2}; do for fam in ${FAMS:-keygen decompile}; do
  echo "=== $MODEL $fam L$lvl $(date +%H:%M:%S)"
  MODE=or MODEL=$MODEL N=${N:-15} FAM=$fam LEVEL=$lvl OFFSET=${OFFSET:-100} sh baselines/run_prompt_c.sh
done; done
