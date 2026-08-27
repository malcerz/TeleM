import csv
import json
import os
import sys
import time
from pathlib import Path

repo_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(repo_root))

from scratch.run_etap3e_benchmarks import run_single_benchmark

print("=" * 90)
print("PHASE 1: CLEAN REF 1000-FRAME BASELINE TEST (AMD_ABOVE_MULTI_RECT=0)")
print("=" * 90)

ref_row, ref_prof = run_single_benchmark("clean_ref_baseline_1000f", "REF", 0, 1000)

print("\n" + "=" * 90)
print("PHASE 1 RESULTS:")
print("=" * 90)
for k, v in ref_row.items():
    print(f"  {k:<25}: {v}")

print(f"\nIS 14 FPS REF FROM 3E REPRODUCIBLE IN CLEAN EXACT CODE?")
if ref_row["calculated_fps"] > 20.0:
    print(f"  -> NO (Clean REF is {ref_row['calculated_fps']:.2f} FPS). The 14 FPS in 3E was caused by intrusive SCAN alpha-scanning on 4.85 MB!")
else:
    print(f"  -> YES (Clean REF is {ref_row['calculated_fps']:.2f} FPS).")
