#!/bin/sh
# Waits for the last cell (formats L3) of gen_sft_data.log to report, then starts the local eval.
until tail -n 1 baselines/logs/gen_sft_data.log | grep -q "formats--deepseek-flash"; do sleep 20; done
sleep 30
sh baselines/run_sft_eval.sh
