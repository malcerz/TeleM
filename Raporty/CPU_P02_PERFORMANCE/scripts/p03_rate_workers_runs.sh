#!/bin/bash
# CPU P0.3: ABR/CRF verification at several bitrates + worker count 2 vs 4 (GUI path, profile driven).
cd /c/_DEV/SportCamHUD/Raporty
D=CPU_P03_PRESETS_AND_RATE_CONTROL
mkdir -p $D/rate $D/workers
R="python CPU_P02_PERFORMANCE/scripts/run_harness.py"
run() { # dir tag frames extra [env...]
  local dir=$1 tag=$2 frames=$3 extra=$4; shift 4
  local envs=(); for e in "$@"; do envs+=(--env "$e"); done
  $R --out-dir $D/$dir --tag $tag --frames $frames --extra "$extra" "${envs[@]}" > /dev/null 2>&1
  sleep 25
}
# Rate control verification (profile balanced = faster)
run rate ABR_8M_300   300 "--profile balanced --bitrate 8M"
run rate ABR_16M_300  300 "--profile balanced --bitrate 16M"
run rate ABR_40M_300  300 "--profile balanced --bitrate 40M"
run rate ABR_80M_300  300 "--profile balanced --bitrate 80M"
run rate CRF_300      300 "--profile balanced --bitrate 40M --cpu-rate-mode crf"
run rate ABR_16M_900  900 "--profile balanced --bitrate 16M"
# Workers 2 vs 4 (profile fast = ultrafast, balanced = faster), 2 repetitions, ABR 16M
for rep in 1 2; do
  for prof in fast balanced; do
    for w in 2 4; do
      run workers W_${prof}_w${w}_r${rep} 300 "--profile $prof --bitrate 16M" TELEM_CPU_WORKERS=$w
    done
  done
done
# Quality profile with automatic worker selection
run workers W_quality_auto_r1 300 "--profile quality --bitrate 16M"
echo done > $D/rate_workers.done
