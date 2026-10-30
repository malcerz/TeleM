#!/bin/sh
# usage: run_matrix.sh PREFIX "900 1800" "1 2 4"
cd C:/GoPro/TO/p10
for s in $2; do for w in $3; do
  t=$1_s${s}_w${w}; d=C:/GoPro/TO/p10/$t
  python hash_harness.py --tag $t --out-dir $d --frames 30 --start-frame $s \
    --env P07A_DIAG_DIR=$d --env P09_START=$s --env P09_CAPTURE_FRAME=15 --env TELEM_CPU_DIAG_DUMP_DIR=$d --env TELEM_CPU_WORKERS=$w \
    --extra "--profile fast --bitrate 16M --golden-dir $d --golden-frame 15 --golden-ready-timeout 60" > $d.summary.txt 2>&1
  echo "$t rc=$?"
done; done
