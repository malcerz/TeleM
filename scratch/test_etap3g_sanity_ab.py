import json
import os
import sys
import time
from pathlib import Path

repo_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(repo_root))

from scratch.run_etap3e_benchmarks import run_single_benchmark

print("=" * 90)
print("PHASE 0: ETAP 3G BAR OPT SANITY ALTERNATING A/B (600 frames each)")
print("=" * 90)

# We can toggle _RULER_WORKING_BUFFERS via environment variable in benchmark
# Let's run 4 alternating runs:
runs = [
    ("ref_3g_bar_1", "REF_3G", 0, 600),
    ("cand_3g_bar_1", "CAND_3G", 1, 600),
    ("ref_3g_bar_2", "REF_3G", 0, 600),
    ("cand_3g_bar_2", "CAND_3G", 1, 600),
]

results = []
for run_id, var, opt_flag, f_count in runs:
    os.environ["AMD_RULER_WORKING_BUFFER"] = str(opt_flag)
    row, prof = run_single_benchmark(run_id, var, 1, f_count)  # AMD_ABOVE_MULTI_RECT=1
    results.append(row)
    print(f"  {run_id:<18} ({var}): Canonical FPS = {row['calculated_fps']:.3f} | Producer = {row['producer_avg_ms']:.3f} ms | Above Compose = {row['above_compose_avg_ms']:.3f} ms")

ref_fps = [r["calculated_fps"] for r in results if r["variant"] == "REF_3G"]
cand_fps = [r["calculated_fps"] for r in results if r["variant"] == "CAND_3G"]
ref_prod = [r["producer_avg_ms"] for r in results if r["variant"] == "REF_3G"]
cand_prod = [r["producer_avg_ms"] for r in results if r["variant"] == "CAND_3G"]

import numpy as np
print("\n" + "=" * 90)
print("PHASE 0 SUMMARY:")
print(f"  REF 3G Median FPS:  {np.median(ref_fps):.3f} FPS | Producer: {np.median(ref_prod):.3f} ms")
print(f"  CAND 3G Median FPS: {np.median(cand_fps):.3f} FPS | Producer: {np.median(cand_prod):.3f} ms")
print(f"  Producer Δ:         {np.median(cand_prod) - np.median(ref_prod):+.3f} ms")
print("=" * 90)
