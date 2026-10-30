#!/bin/bash
# Sequential x265 preset sweep (decode + x265, no HUD), CRF24 and ABR 16384k.
cd /c/_DEV/SportCamHUD/Raporty/CPU_P02_PERFORMANCE
for rc in crf24 abr16384; do
  for p in medium fast faster veryfast ultrafast; do
    tag="X_${p}_${rc}_150"
    python scripts/bench_ffmpeg.py x265 --preset $p --rc $rc --out-dir presets --tag $tag
    sleep 20   # cool-down between runs (laptop APU)
  done
done
for rc in crf24 abr16384; do
  for p in medium fast faster veryfast ultrafast; do
    python scripts/quality.py presets/X_${p}_${rc}_150.mp4
  done
done
echo SWEEP_DONE
