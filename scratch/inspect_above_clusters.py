import json
import os
import sys
from pathlib import Path

repo_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(repo_root))

from src.indicators.compositor import compose_overlay
from src.ffmpeg.amd_native_exporter import (
    _ordered_map_layout_parts,
    _cluster_above_bboxes_members,
    _cluster_above_bboxes,
    _extract_exact_above_regions,
    _extract_above_regions,
)

layout = json.load(open(repo_root / "def_layout.json", encoding="utf-8"))
w, h = 3840, 2160
font_path = "arial.ttf"

compose_layout, map_above_layout, map_after_keys = _ordered_map_layout_parts(layout)

print("=" * 90)
print("INSPECTING CPU ABOVE WIDGETS AND BOUNDING BOXES (def_layout.json)")
print("=" * 90)

print(f"map_above_layout indicators: {list(map_above_layout.get('indicators', {}).keys())}")

# Simulate frame render
above_bboxes = {}
above_tight_bboxes = {}

# Remove after-map keys (charts/gauge)
above_capture_keys = {"fit_cadence_text", "fit_heart_rate_text", "speed_text"}

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

print(f"\nRendered above_bboxes ({len(above_bboxes)} items):")
for k, b in above_bboxes.items():
    tb = above_tight_bboxes.get(k)
    print(f"  {k:<25}: bbox={b}, tight_bbox={tb.get('rect') if tb else None}")

clusters = _cluster_above_bboxes_members(above_bboxes, w, h, pad=16, merge_dist=32, max_regions=16)
print(f"\n_cluster_above_bboxes_members generated {len(clusters)} cluster(s):")
total_cluster_area = 0
for idx, (c_rect, members) in enumerate(clusters):
    cx, cy, cw, ch = c_rect
    area = cw * ch
    total_cluster_area += area
    print(f"  Cluster {idx}: rect=({cx}, {cy}, {cw}, {ch}) [{cw}x{ch} = {area:,} px = {area*4/1024/1024:.2f} MB], members={members}")

regions_out, stats = _extract_exact_above_regions(
    above_full, clusters, above_tight_bboxes, w, h
)

print(f"\n_extract_exact_above_regions output:")
print(f"  Region count:    {len(regions_out)}")
total_reg_bytes = 0
for idx, (rx, ry, rw, rh, rbytes) in enumerate(regions_out):
    total_reg_bytes += len(rbytes)
    print(f"  Region {idx}: ({rx}, {ry}, {rw}, {rh}) -> {rw*rh:,} px ({len(rbytes):,} bytes = {len(rbytes)/1024/1024:.2f} MB)")

print(f"\nTotal uploaded bytes: {total_reg_bytes:,} bytes ({total_reg_bytes/1024/1024:.2f} MB)")

# Now compare if we had independent widget bboxes (without excessive clustering / single union)
print("\n" + "=" * 90)
print("INDEPENDENT WIDGET RECTS COMPARISON")
print("=" * 90)
indep_bytes = 0
for k, tb in above_tight_bboxes.items():
    if tb and tb.get("rect"):
        rx, ry, rw, rh = tb["rect"]
        b_size = rw * rh * 4
        indep_bytes += b_size
        print(f"  {k:<25}: {rw}x{rh} = {rw*rh:,} px ({b_size:,} bytes = {b_size/1024:.1f} KB)")

print(f"Total independent widget bytes: {indep_bytes:,} bytes ({indep_bytes/1024/1024:.2f} MB)")
print(f"Ratio (Clusters / Independent): {total_reg_bytes / indep_bytes:.2f}x")
