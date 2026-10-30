#!/bin/bash
# Same segment (start 900, 300 frames, medium): old 15 workers vs new auto selection.
cd /c/_DEV/SportCamHUD/Raporty/CPU_P02_PERFORMANCE
python scripts/run_harness.py --tag BEFORE_medium_w15_300 --out-dir beforeafter --frames 300 --env TELEM_CPU_WORKERS=15 > /dev/null 2>&1
sleep 25
python scripts/run_harness.py --tag AFTER_medium_auto_300 --out-dir beforeafter --frames 300 > /dev/null 2>&1
sleep 25
python scripts/run_harness.py --tag BEFORE_medium_w15_300_r2 --out-dir beforeafter --frames 300 --env TELEM_CPU_WORKERS=15 > /dev/null 2>&1
sleep 25
python scripts/run_harness.py --tag AFTER_medium_auto_300_r2 --out-dir beforeafter --frames 300 > /dev/null 2>&1
echo done > beforeafter.done
