#!/bin/sh
# Second teacher pass (new train seeds 30+), low concurrency so it can run beside the local eval.
FAMS="formats" LEVELS="0" OFFSET=30 N=40 C=2 sh baselines/gen_sft_data.sh
FAMS="decompile keygen" LEVELS="0 1 2 3 4" OFFSET=30 N=30 C=2 sh baselines/gen_sft_data.sh
