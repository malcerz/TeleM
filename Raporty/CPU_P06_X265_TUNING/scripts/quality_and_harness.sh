#!/bin/bash
# CPU P0.6: (1) quality vs lossless for candidates, (2) real-export harness confirmation (ultrafast base vs lookahead-threads=4).
cd /c/_DEV/SportCamHUD/Raporty/CPU_P06_X265_TUNING
mkdir -p q harness
B="python scripts/bench_x265.py --frames 150 --keep"
# bench writes to sweeps/; use dedicated tags and move
$B --preset ultrafast --tag q_ref_lossless --crf 24 --x265 "lossless=1" > /dev/null 2>&1; sleep 10
$B --preset ultrafast --tag q_u_base > /dev/null 2>&1; sleep 10
$B --preset ultrafast --tag q_u_lat4 --x265 "lookahead-threads=4" > /dev/null 2>&1; sleep 10
$B --preset ultrafast --tag q_u_ft6_lat4 --x265 "frame-threads=6:lookahead-threads=4" > /dev/null 2>&1; sleep 10
$B --preset ultrafast --tag q_u_bf1 --x265 "bframes=1" > /dev/null 2>&1; sleep 10
$B --preset faster --tag q_f_base > /dev/null 2>&1; sleep 10
$B --preset faster --tag q_f_ctu32 --x265 "ctu=32" > /dev/null 2>&1; sleep 10
$B --preset faster --tag q_f_bf2 --x265 "bframes=2" > /dev/null 2>&1; sleep 10
md5sum sweeps/q_u_base.mp4 sweeps/q_u_lat4.mp4 > q/md5_base_vs_lat4.txt
python ../CPU_P02_PERFORMANCE/scripts/region_quality.py sweeps sweeps/q_ref_lossless.mp4 q_u_base q_u_lat4 q_u_ft6_lat4 q_u_bf1 q_f_base q_f_ctu32 q_f_bf2 > q/region_quality.log 2>&1
cp sweeps/region_quality.json q/region_quality.json
ls -la sweeps/q_*.mp4 | awk '{print $5, $9}' > q/sizes.txt
rm -f sweeps/q_*.mp4
# harness confirmation on the real export (workers + HUD changing per frame), interleaved
W=$(cygpath -w $PWD)
for rep in 1 2 3; do
  python ../CPU_P02_PERFORMANCE/scripts/run_harness.py --out-dir harness --tag H_fast_base_r$rep --frames 300 --extra "--profile fast --bitrate 16M" > /dev/null 2>&1; rm -f harness/H_fast_base_r$rep.mp4; sleep 20
  python ../CPU_P02_PERFORMANCE/scripts/run_harness.py --out-dir harness --tag H_fast_lat4_r$rep --frames 300 --env "TELEM_CPU_X265_PARAMS=lookahead-threads=4" --extra "--profile fast --bitrate 16M" > /dev/null 2>&1; rm -f harness/H_fast_lat4_r$rep.mp4; sleep 20
done
echo done > q/all.done
