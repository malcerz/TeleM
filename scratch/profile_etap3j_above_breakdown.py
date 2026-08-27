import json
import os
import sys
import time
from pathlib import Path

repo_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(repo_root))

from PIL import Image, ImageDraw
import numpy as np

from src.gui.telemetry_manager import TelemetryDataManager
from src.telemetry_processed_cache import read_processed_cache, apply_processed_cache
from src.indicators.compositor import compose_overlay, _get_reusable_canvas
from src.ffmpeg.amd_native_exporter import (
    _ordered_map_layout_parts,
    _cluster_above_bboxes_members,
    _extract_exact_above_regions,
)

VIDEO = repo_root / "Video" / "GX030120.MP4"
FIT = repo_root / "Video" / "Jazda_na_rowerze_w_porze_lunchu.fit"
layout = json.load(open(repo_root / "def_layout.json", encoding="utf-8"))

tm = TelemetryDataManager()
processed = read_processed_cache(VIDEO)
if processed is not None:
    apply_processed_cache(tm, processed)
else:
    tm.load_gpmf_from_exiftool(VIDEO)
tm.load_fit(VIDEO, start_dt=tm.start_dt_utc, manual_path=FIT)

w, h = 3840, 2160
font_path = "arial.ttf"
fps = 30000.0 / 1001.0

compose_layout, map_above_layout, map_after_keys = _ordered_map_layout_parts(layout)
gpu_chart_keys = {"fit_cadence_text", "fit_heart_rate_text"}
gpu_gauge_key = "speed_text"
above_capture_keys = gpu_chart_keys | {gpu_gauge_key}

print("=" * 90)
print("PHASE 2 & 3 & 4: CPU ABOVE COMPOSE DECONSTRUCTION & PROFILING (300 FRAMES)")
print("=" * 90)

substage_times = {
    "canvas_alloc": [],
    "canvas_clear": [],
    "widget_render_total": [],
    "widget_composite_total": [],
    "tight_bbox_getchannel": [],
    "multi_rect_cluster": [],
    "multi_rect_crop": [],
    "multi_rect_tobytes": [],
    "above_total": [],
}

large_ops = {
    "4k_allocs": 0,
    "4k_clears": 0,
    "crops_total": 0,
    "crops_pixels": 0,
    "tobytes_total": 0,
    "tobytes_bytes": 0,
}

per_widget_render = {}
per_widget_composite = {}

for frame_idx in range(300):
    t_frame_start = time.perf_counter()
    t_sec = frame_idx / fps
    d_samp = tm.track_samples
    d_idx = min(len(d_samp) - 1, int(t_sec * 10)) if d_samp else 0
    dist_m = d_samp[d_idx][1] if d_samp else 0.0
    alt_m = 250.0 + (frame_idx * 0.2) % 500.0
    temp_c = 22.0 + (frame_idx // 100) % 5
    iso_val = 100 if frame_idx < 1000 else 200
    exp_val = 240.0 if frame_idx < 1000 else 480.0

    above_bboxes = {}
    above_tight_bboxes = {}

    t_compose_start = time.perf_counter()
    above_full = compose_overlay(
        canvas_w=w, canvas_h=h, layout=map_above_layout, font_path=font_path,
        date_text="2026-08-26", time_text=f"12:{frame_idx//1800:02d}:{(frame_idx//30)%60:02d}",
        speed_value=25.0 + np.sin(frame_idx / 20.0) * 10.0, distance_m=dist_m,
        alt_value=alt_m, temp_value=temp_c, iso_value=iso_val, exposure_value=exp_val,
        _bboxes=above_bboxes, _tight_bboxes=above_tight_bboxes,
        gpu_capture_keys=above_capture_keys, gpu_capture={}, reuse_canvas="above",
    )
    t_compose_end = time.perf_counter()
    substage_times["above_total"].append((t_compose_end - t_compose_start) * 1000.0)

    # Multi-rect extraction
    t_plan_start = time.perf_counter()
    clusters_with_members = _cluster_above_bboxes_members(
        above_bboxes, w, h, pad=16, merge_dist=32, max_regions=8
    )
    t_plan_end = time.perf_counter()
    substage_times["multi_rect_cluster"].append((t_plan_end - t_plan_start) * 1000.0)

    regions_out, stats_p = _extract_exact_above_regions(
        above_full, clusters_with_members, above_tight_bboxes or {}, w, h,
    )
    substage_times["multi_rect_crop"].append(stats_p.get("exact_crop_ms", 0.0))
    substage_times["multi_rect_tobytes"].append(stats_p.get("tobytes_ms", 0.0))

print("\n--- TIMING BREAKDOWN (300 FRAMES) ---")
for k, v in substage_times.items():
    if v:
        print(f"  {k:<28}: AVG {np.mean(v):6.3f} ms | Median {np.median(v):6.3f} ms | P95 {np.percentile(v, 95):6.3f} ms")

print("\n--- ABOVE WIDGETS IN DEF_LAYOUT ---")
for k, box in above_bboxes.items():
    print(f"  Widget {k:<25}: bbox={box}, pixels={box[2]*box[3]:8d} ({box[2]*box[3]*4/1024:.1f} KB)")
