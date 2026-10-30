#!/bin/bash
# CPU P0.4 stage 3: workers 2 vs 4 in all three profiles, ABR 16M, 300 frames, 2 reps, interleaved.
cd /c/_DEV/SportCamHUD/Raporty
D=CPU_P04_GUI_GOLDEN_OVERLAY/workers
mkdir -p $D
for rep in 1 2; do
  for prof in fast balanced quality; do
    for w in 2 4; do
      python CPU_P02_PERFORMANCE/scripts/run_harness.py --out-dir $D --tag W_${prof}_w${w}_r${rep} --frames 300 \
        --env TELEM_CPU_WORKERS=$w --extra "--profile $prof --bitrate 16M" > /dev/null 2>&1
      rm -f $D/W_${prof}_w${w}_r${rep}.mp4
      sleep 25
    done
  done
done
echo done > $D/../workers.done
