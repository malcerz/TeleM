#!/bin/bash
# CPU P0.4: three profiles, same 160-frame segment, ABR 16M, pre-compression HUD dump of frame 150.
cd /c/_DEV/SportCamHUD/Raporty/CPU_P04_GUI_GOLDEN_OVERLAY
W=$(cygpath -w $PWD)
for prof in fast balanced quality; do
  mkdir -p golden_run/$prof
  python ../CPU_P02_PERFORMANCE/scripts/run_harness.py --out-dir golden_run --tag P_$prof --frames 160 \
    --env "TELEM_CPU_DIAG_DUMP_FRAMES=150" --env "TELEM_CPU_DIAG_DUMP_DIR=$W\\golden_run\\$prof" \
    --extra "--profile $prof --bitrate 16M" > /dev/null 2>&1
  sleep 25
done
echo done > golden_run/profiles.done
