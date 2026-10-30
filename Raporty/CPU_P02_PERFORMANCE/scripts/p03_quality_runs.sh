#!/bin/bash
# CPU P0.3: lossless reference + 4 presets x 2 ABR bitrates, full HUD, 300 frames, via GUI path.
cd /c/_DEV/SportCamHUD/Raporty
D=CPU_P03_PRESETS_AND_RATE_CONTROL
mkdir -p $D/quality
H="python CPU_P02_PERFORMANCE/scripts/run_harness.py --out-dir $D/quality --frames 300"
$H --tag REF_lossless --env TELEM_CPU_X265_PRESET=ultrafast --env "TELEM_CPU_X265_PARAMS=lossless=1" --extra "--cpu-rate-mode crf" > /dev/null 2>&1
sleep 20
for br in 16M 40M; do
  for p in medium fast faster ultrafast; do
    $H --tag Q_${p}_${br} --env TELEM_CPU_X265_PRESET=$p --extra "--bitrate $br" > /dev/null 2>&1
    sleep 25
  done
done
echo done > $D/quality.done
