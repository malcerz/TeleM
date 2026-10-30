#!/bin/bash
# CPU P0.6 sweep 3: repeatability of the ultrafast candidates (4 interleaved reps) + faster ctu32/bf6 sanity.
cd /c/_DEV/SportCamHUD/Raporty/CPU_P06_X265_TUNING
LOG=sweeps/sweep_repeat.log
: > $LOG
run() {
  python scripts/bench_x265.py --preset $1 --tag $2 --x265 "$3" --frames 300 2>&1 | tail -1 | python -c "
import sys,json;d=json.loads(sys.stdin.read());print(d['tag'],'wall',d['wall_fps'],'steady',d.get('steady_fps'),'x265',d.get('x265_fps'),'util%',d.get('cpu_util_pct_of_16'),'core_s/f',d.get('core_s_per_frame'),'rssMB',d.get('rss_peak_mb'),'kbps',d.get('x265_kbps'),'first',d.get('first_frame_s'),'fin',d.get('finalize_s'),d.get('errors'))" | tee -a $LOG
  sleep 8
}
for rep in 1 2 3 4; do
  run ultrafast r${rep}_base ""
  run ultrafast r${rep}_lat4 "lookahead-threads=4"
  run ultrafast r${rep}_ft6_lat4 "frame-threads=6:lookahead-threads=4"
  run ultrafast r${rep}_ft8_lat4 "frame-threads=8:lookahead-threads=4"
  run ultrafast r${rep}_lat5 "lookahead-threads=5"
done
for rep in 1 2; do
  run faster rf${rep}_base ""
  run faster rf${rep}_ctu32 "ctu=32"
done
echo done > sweeps/sweep_repeat.done
