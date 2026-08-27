import json
import os
import sys
import time
from pathlib import Path

repo_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(repo_root))

from src.indicators.compositor import compose_overlay
from src.ffmpeg.amd_native_exporter import (
    _ordered_map_layout_parts,
    _rendered_bbox_union,
    _extract_above_regions,
    _extract_exact_above_regions,
    _cluster_above_bboxes_members,
)

layout = json.load(open(repo_root / "def_layout.json", encoding="utf-8"))
w, h = 3840, 2160
font_path = "arial.ttf"

compose_layout, map_above_layout, map_after_keys = _ordered_map_layout_parts(layout)
above_capture_keys = {"fit_cadence_text", "fit_heart_rate_text", "speed_text"}

above_bboxes = {}
above_tight_bboxes = {}

above_full = compose_overlay(
    canvas_w=w,
    canvas_h=h,
    layout=map_above_layout,
    font_path=font_path,
    date_text="2026-08-26",
    time_text="12:00:00",
    speed_value=25.4,
    distance_m=12345.0,
    _bboxes=above_bboxes,
    _tight_bboxes=above_tight_bboxes,
    gpu_capture_keys=above_capture_keys,
    gpu_capture={},
    reuse_canvas=False,
)

print("=" * 90)
print("DIAGNOSING 3E REF 14 FPS ANOMALY ROOT CAUSE")
print("=" * 90)

# 1. Measure 3E REF mode: Single Union with _extract_above_regions (triggers 4.85 MB alpha scan)
cand = _rendered_bbox_union(above_bboxes, w, h, pad=64)
candidate_clusters = [cand] if cand is not None else []

times_scan = []
for _ in range(50):
    t0 = time.perf_counter()
    res, stats = _extract_above_regions(above_full, candidate_clusters, "SCAN")
    times_scan.append((time.perf_counter() - t0) * 1000.0)

print(f"3E REF (Single Union + SCAN full-frame alpha scan):")
print(f"  Total time:     {sum(times_scan)/len(times_scan):.3f} ms")
print(f"  candidate_crop: {stats['candidate_crop_ms']:.3f} ms")
print(f"  alpha_scan:     {stats['alpha_scan_ms']:.3f} ms  <-- 4.85 MILLION ALPHA BYTES SCAN!")
print(f"  final_crop:     {stats['final_crop_ms']:.3f} ms")
print(f"  tobytes:        {stats['tobytes_ms']:.3f} ms")
print(f"  uploaded_bytes: {stats['uploaded_bytes']:,} bytes ({stats['uploaded_bytes']/1024/1024:.2f} MB)")

# 2. Measure Single Union with EXACT (no alpha scan)
# If single union was done with exact union (no alpha scan)
t_union_exact = []
for _ in range(50):
    t0 = time.perf_counter()
    ux, uy, uw, uh = cand
    reg_img = above_full.crop((ux, uy, ux + uw, uy + uh))
    r_bytes = reg_img.tobytes("raw", "RGBA")
    t_union_exact.append((time.perf_counter() - t0) * 1000.0)

print(f"\nClean Single Union EXACT (Direct Crop + ToBytes, NO alpha scan):")
print(f"  Total time:     {sum(t_union_exact)/len(t_union_exact):.3f} ms (Crop+ToBytes)")
print(f"  uploaded_bytes: {len(r_bytes):,} bytes ({len(r_bytes)/1024/1024:.2f} MB)")

# 3. Measure Multi-Rect EXACT (4 clusters, no alpha scan)
clusters_with_members = _cluster_above_bboxes_members(above_bboxes, w, h, pad=16, merge_dist=32, max_regions=8)
times_multi = []
for _ in range(50):
    t0 = time.perf_counter()
    res_m, stats_m = _extract_exact_above_regions(above_full, clusters_with_members, above_tight_bboxes, w, h)
    times_multi.append((time.perf_counter() - t0) * 1000.0)

print(f"\nMulti-Rect EXACT (4 disjoint clusters, Direct Crop + ToBytes):")
print(f"  Total time:     {sum(times_multi)/len(times_multi):.3f} ms")
print(f"  exact_crop:     {stats_m['exact_crop_ms']:.3f} ms")
print(f"  tobytes:        {stats_m['tobytes_ms']:.3f} ms")
print(f"  uploaded_bytes: {stats_m['uploaded_bytes']:,} bytes ({stats_m['uploaded_bytes']/1024/1024:.2f} MB)")
