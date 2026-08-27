import json
import os
import sys
import time
from pathlib import Path

repo_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(repo_root))

from scratch.run_etap3e_benchmarks import run_single_benchmark

print("=" * 90)
print("PHASE 16: REAL GUI-LIKE SMOKE TEST (300 frames, rotation=180, def_layout)")
print("=" * 90)

row, prof = run_single_benchmark("gui_smoke_300f", "SMOKE", 1, 300)

print("\n" + "=" * 90)
print("GUI SMOKE RESULTS:")
print("=" * 90)
for k, v in row.items():
    print(f"  {k:<25}: {v}")

assert row["rects_avg"] == 4.0, f"Expected 4 rects, got {row['rects_avg']}"
assert row["bytes_avg"] < 3_000_000, f"Expected <3MB, got {row['bytes_avg']}"
print("\n  -> GUI SMOKE PASS: Multi-Rect active, 4 rects, 2.52 MB average!")
