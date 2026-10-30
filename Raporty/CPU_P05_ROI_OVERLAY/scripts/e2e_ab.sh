#!/bin/bash
# CPU P0.5: FFmpeg-side end-to-end A/B (real x265) of full-frame overlay vs ROI plans. Sequential, interleaved.
cd /c/_DEV/SportCamHUD/Raporty/CPU_P05_ROI_OVERLAY
run() { # layout variant sink tag extra...
  local lay=$1 var=$2 sink=$3 tag=$4; shift 4
  python scripts/prototype_roi.py time $lay 160 $var --sink $sink --frames 300 --tag $tag "$@" 2>&1 | tail -1 | python -c "
import sys,json;d=json.loads(sys.stdin.read());print('$tag','$lay','$var','$sink','regions',d.get('regions'),'area',d.get('region_pct'),'wall_fps',d['wall_fps'],'steady',d.get('steady_fps'),'x265',d.get('x265_fps'),'core_s/f',d.get('core_s_per_frame'),'rssMB',d.get('rss_peak_mb'),d.get('errors'))" | tee -a e2e_ab.log
  rm -f proto/$tag.mp4; sleep 15
}
: > e2e_ab.log
for rep in 1 2 3; do
  run def full ultrafast E_def_full_uf_r$rep
  run def roi_each ultrafast E_def_roi11_uf_r$rep --tile 16 --overhead 60000
  run def roi_each ultrafast E_def_roi2_uf_r$rep --tile 16 --overhead 500000
done
for rep in 1 2; do
  run v10 full ultrafast E_v10_full_uf_r$rep
  run v10 roi_each ultrafast E_v10_roi1_uf_r$rep --tile 16 --overhead 500000
  run v3 full ultrafast E_v3_full_uf_r$rep
  run v3 roi_each ultrafast E_v3_roi5_uf_r$rep --tile 16 --overhead 500000
  run def full faster E_def_full_fa_r$rep
  run def roi_each faster E_def_roi2_fa_r$rep --tile 16 --overhead 500000
done
echo done > e2e_ab.done
