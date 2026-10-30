#!/bin/bash
# CPU P0.6 sweep 2: lookahead-threads neighbourhood + quality-related knobs (measured, not assumed).
cd /c/_DEV/SportCamHUD/Raporty/CPU_P06_X265_TUNING
LOG=sweeps/sweep_lookahead.log
: > $LOG
run() {
  python scripts/bench_x265.py --preset $1 --tag $2 --x265 "$3" --frames 300 2>&1 | tail -1 | python -c "
import sys,json;d=json.loads(sys.stdin.read());print(d['tag'],'wall',d['wall_fps'],'steady',d.get('steady_fps'),'x265',d.get('x265_fps'),'util%',d.get('cpu_util_pct_of_16'),'core_s/f',d.get('core_s_per_frame'),'rssMB',d.get('rss_peak_mb'),'kbps',d.get('x265_kbps'),'first',d.get('first_frame_s'),'fin',d.get('finalize_s'),d.get('errors'))" | tee -a $LOG
  sleep 8
}
preset=ultrafast
run $preset u2_base_a ""
for spec in "lat3:lookahead-threads=3" "lat4:lookahead-threads=4" "lat5:lookahead-threads=5" "lat6:lookahead-threads=6" "lat8:lookahead-threads=8" \
            "ft2_lat4:frame-threads=2:lookahead-threads=4" "ft3_lat4:frame-threads=3:lookahead-threads=4" "ft6_lat4:frame-threads=6:lookahead-threads=4" \
            "lat4_pools12:lookahead-threads=4:pools=12" "lat4_las4:lookahead-threads=4:lookahead-slices=4" \
            "rcla10:rc-lookahead=10" "rcla20:rc-lookahead=20" "bf0:bframes=0" "bf1:bframes=1" "bf6:bframes=6" \
            "sc0:scenecut=0" "ctu32:ctu=32" "lat4_ctu32:lookahead-threads=4:ctu=32"; do
  run $preset u2_${spec%%:*} "${spec#*:}"
  case "${spec%%:*}" in lat6|ft6_lat4) run $preset u2_base_$(date +%s) "";; esac
done
run $preset u2_base_z ""
preset=faster
run $preset f2_base_a ""
for spec in "lat3:lookahead-threads=3" "lat6:lookahead-threads=6" "lat8:lookahead-threads=8" "ft3_lat4:frame-threads=3:lookahead-threads=4" \
            "rcla5:rc-lookahead=5" "rcla30:rc-lookahead=30" "bf2:bframes=2" "bf6:bframes=6" "sc0:scenecut=0" "ctu32:ctu=32" "ref2:ref=2"; do
  run $preset f2_${spec%%:*} "${spec#*:}"
done
run $preset f2_base_z ""
echo done > sweeps/sweep_lookahead.done
