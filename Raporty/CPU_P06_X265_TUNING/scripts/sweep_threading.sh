#!/bin/bash
# CPU P0.6 sweep 1: x265 threading knobs (quality-neutral). Sequential, base interleaved to monitor drift.
cd /c/_DEV/SportCamHUD/Raporty/CPU_P06_X265_TUNING
LOG=sweeps/sweep_threading.log
: > $LOG
run() { # preset tag params
  python scripts/bench_x265.py --preset $1 --tag $2 --x265 "$3" --frames 300 2>&1 | tail -1 | python -c "
import sys,json;d=json.loads(sys.stdin.read());print(d['tag'],'wall',d['wall_fps'],'steady',d.get('steady_fps'),'x265',d.get('x265_fps'),'util%',d.get('cpu_util_pct_of_16'),'core_s/f',d.get('core_s_per_frame'),'rssMB',d.get('rss_peak_mb'),'kbps',d.get('x265_kbps'),'first',d.get('first_frame_s'),'fin',d.get('finalize_s'),d.get('errors'))" | tee -a $LOG
  sleep 8
}
for preset in ultrafast faster; do
  run $preset ${preset}_base_a ""
  for spec in "ft2:frame-threads=2" "ft3:frame-threads=3" "ft5:frame-threads=5" "ft6:frame-threads=6" "ft8:frame-threads=8" \
              "pools8:pools=8" "pools12:pools=12" "wpp0:wpp=0" "wpp0_ft8:wpp=0:frame-threads=8" \
              "las0:lookahead-slices=0" "las4:lookahead-slices=4" "lat2:lookahead-threads=2" "lat4:lookahead-threads=4" \
              "pmode:pmode=1" "pme:pme=1"; do
    tag=${spec%%:*}; params=${spec#*:}
    run $preset ${preset}_${tag} "$params"
    if [ "$tag" = "pools12" ] || [ "$tag" = "las4" ]; then run $preset ${preset}_base_mid_$tag ""; fi
  done
  run $preset ${preset}_base_z ""
done
echo done > sweeps/sweep_threading.done
