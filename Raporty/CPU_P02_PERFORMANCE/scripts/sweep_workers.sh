#!/bin/bash
# Sequential full-pipeline worker-count sweep (harness D), medium and ultrafast.
cd /c/_DEV/SportCamHUD/Raporty/CPU_P02_PERFORMANCE
for cfg in "medium 150" "ultrafast 300"; do
  set -- $cfg; preset=$1; frames=$2
  for w in 2 4 8 15; do
    python scripts/run_harness.py --tag "W_${preset}_w${w}_${frames}" --out-dir workers --frames $frames \
      --env TELEM_CPU_WORKERS=$w --env TELEM_CPU_X265_PRESET=$preset > /dev/null 2>&1
    sleep 20
  done
done
echo WORKERS_DONE > workers_sweep.done
