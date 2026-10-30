#!/bin/bash
# CPU P0.5: dump real pre-compression HUD frames (RGBA, stored orientation) for 3 layouts x 5 timestamps.
cd /c/_DEV/SportCamHUD/Raporty/CPU_P05_ROI_OVERLAY
W=$(cygpath -w $PWD)
FR="0,80,160,240,319"
for spec in "def:C:\\_DEV\\SportCamHUD\\def_layout.json" "v10:C:\\_DEV\\SportCamHUD\\presets\\cycling_dashboard_v10.json" "v3:C:\\_DEV\\SportCamHUD\\presets\\cycling_dashboard_v3.json"; do
  name=${spec%%:*}; lay=${spec#*:}
  mkdir -p frames/$name
  python ../CPU_P02_PERFORMANCE/scripts/run_harness.py --out-dir frames --tag run_$name --frames 320 \
    --env "TELEM_CPU_DIAG_DUMP_FRAMES=$FR" --env "TELEM_CPU_DIAG_DUMP_DIR=$W\\frames\\$name" \
    --extra "--profile fast --bitrate 16M --layout $lay" > /dev/null 2>&1
  rm -f frames/run_$name.mp4
  sleep 20
done
echo done > frames/dump.done
