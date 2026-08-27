import json
import os
import sys
import time
from pathlib import Path

repo_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(repo_root))

from scratch.run_etap3e_benchmarks import run_single_benchmark

print("=" * 90)
print("PHASE 28: 300-FRAME DEV BENCHMARK (REF FULL-WIDGET MULTI vs CAND FINE DIRTY)")
print("=" * 90)

# Run 1: REF (AMD_ABOVE_FINE_DIRTY=0)
os.environ["AMD_ABOVE_FINE_DIRTY"] = "0"
os.environ["AMD_ABOVE_MULTI_RECT"] = "1"
os.environ["AMD_LEAN_GPU"] = "0"
row_ref, prof_ref = run_single_benchmark("dev_bench_ref_300f", "REF_FULL_WIDGET", 1, 300)

# Run 2: CAND (AMD_ABOVE_FINE_DIRTY=1)
os.environ["AMD_ABOVE_FINE_DIRTY"] = "1"
os.environ["AMD_ABOVE_MULTI_RECT"] = "1"
os.environ["AMD_LEAN_GPU"] = "0"
row_cand, prof_cand = run_single_benchmark("dev_bench_cand_300f", "CAND_FINE_DIRTY", 1, 300)

print("\n" + "=" * 90)
print(f"{'Metric':<32} {'REF (Full Multi-Rect)':<24} {'CAND (Fine Dirty)':<24} {'Delta / %':<16}")
print("-" * 90)

fps_ref = row_ref["calculated_fps"]
fps_cand = row_cand["calculated_fps"]
fps_delta = fps_cand - fps_ref
fps_pct = (fps_delta / fps_ref) * 100.0 if fps_ref > 0 else 0.0

prod_ref = row_ref["producer_avg_ms"]
prod_cand = row_cand["producer_avg_ms"]

ab_comp_ref = row_ref["above_compose_avg_ms"]
ab_comp_cand = row_cand["above_compose_avg_ms"]

crop_ref = row_ref.get("multi_crop_avg", 0.0)
crop_cand = row_cand.get("multi_crop_avg", 0.0)

tb_ref = row_ref.get("multi_tobytes_avg", 0.0)
tb_cand = row_cand.get("multi_tobytes_avg", 0.0)

up_ref = row_ref.get("multi_upload_avg", 0.0)
up_cand = row_cand.get("multi_upload_avg", 0.0)

b_ref = prof_ref.get("above_map_stats", {}).get("uploaded_bytes_avg", 0.0)
b_cand = prof_cand.get("above_map_stats", {}).get("uploaded_bytes_avg", 0.0)
b_red = (1.0 - (b_cand / b_ref if b_ref > 0 else 1.0)) * 100.0

r_ref = prof_ref.get("above_map_stats", {}).get("region_count_avg", 0.0)
r_cand = prof_cand.get("above_map_stats", {}).get("region_count_avg", 0.0)

print(f"{'Canonical Render FPS':<32} {fps_ref:<24.3f} {fps_cand:<24.3f} {fps_delta:+.3f} ({fps_pct:+.1f}%)")
print(f"{'Producer Prepare avg (ms)':<32} {prod_ref:<24.3f} {prod_cand:<24.3f} {prod_cand - prod_ref:+.3f} ms")
print(f"{'Above Compose avg (ms)':<32} {ab_comp_ref:<24.3f} {ab_comp_cand:<24.3f} {ab_comp_cand - ab_comp_ref:+.3f} ms")
print(f"{'Above Exact Crop (ms)':<32} {crop_ref:<24.3f} {crop_cand:<24.3f} {crop_cand - crop_ref:+.3f} ms")
print(f"{'Above Tobytes (ms)':<32} {tb_ref:<24.3f} {tb_cand:<24.3f} {tb_cand - tb_ref:+.3f} ms")
print(f"{'Above Upload avg (ms)':<32} {up_ref:<24.3f} {up_cand:<24.3f} {up_cand - up_ref:+.3f} ms")
print(f"{'Above Uploaded Bytes/Frame':<32} {b_ref:<24.0f} {b_cand:<24.0f} {-b_red:+.1f}%")
print(f"{'Above Region Count/Frame':<32} {r_ref:<24.1f} {r_cand:<24.1f} {r_cand - r_ref:+.1f}")
print("=" * 90)
