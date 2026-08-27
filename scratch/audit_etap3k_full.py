import csv
import json
import os
import sys
import time
from collections import defaultdict
from pathlib import Path

repo_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(repo_root))

from PIL import Image, ImageDraw
import numpy as np

from src.gui.telemetry_manager import TelemetryDataManager
from src.telemetry_processed_cache import read_processed_cache, apply_processed_cache
from src.indicators.compositor import compose_overlay
from src.indicators.dispatcher import render_value_indicator
from src.indicators.rotated_paste import rotated_paste, reset_tight_bbox_collect, get_tight_bbox_collect_ms
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

# Disable CPU bike graphic since AMD_LEAN_GPU=1 is active
if "indicators" in map_above_layout and "lean_indicator" in map_above_layout["indicators"]:
    map_above_layout["indicators"]["lean_indicator"]["enabled"] = False

gpu_chart_keys = {"fit_cadence_text", "fit_heart_rate_text"}
gpu_gauge_key = "speed_text"
above_capture_keys = gpu_chart_keys | {gpu_gauge_key}

OUT_DIR = repo_root / "Raporty" / "AMD_ETAP_3K"
OUT_DIR.mkdir(parents=True, exist_ok=True)

print("=" * 90)
print("AMD ETAP 3K — PHASE 1 to 6: PROFILER AUDIT & EXACT PER-CALL TIMING (600 FRAMES)")
print("=" * 90)

widget_calls_count = defaultdict(int)
widget_timing_records = []
frame_summary = []

for frame_idx in range(600):
    t_sec = frame_idx / fps
    d_samp = tm.track_samples
    d_idx = min(len(d_samp) - 1, int(t_sec * 10)) if d_samp else 0
    dist_m = d_samp[d_idx][1] if d_samp else 0.0
    alt_m = 250.0 + (frame_idx * 0.2) % 500.0
    temp_c = 22.0 + (frame_idx // 100) % 5
    iso_val = 100 if frame_idx < 1000 else 200
    exp_val = 240.0 if frame_idx < 1000 else 480.0

    frame_kwargs = {
        "date_text": "2026-08-26",
        "time_text": f"12:{frame_idx//1800:02d}:{(frame_idx//30)%60:02d}",
        "speed_value": 25.0 + np.sin(frame_idx / 20.0) * 10.0,
        "distance_m": dist_m,
        "alt_value": alt_m,
        "temp_value": temp_c,
        "iso_value": iso_val,
        "exposure_value": exp_val,
    }

    above_bboxes = {}
    above_tight_bboxes = {}
    reset_tight_bbox_collect()

    t_above_start = time.perf_counter()
    above_full = compose_overlay(
        canvas_w=w, canvas_h=h, layout=map_above_layout, font_path=font_path,
        _bboxes=above_bboxes, _tight_bboxes=above_tight_bboxes,
        gpu_capture_keys=above_capture_keys, gpu_capture={}, reuse_canvas="above",
        **frame_kwargs
    )
    t_above_end = time.perf_counter()
    above_compose_ms = (t_above_end - t_above_start) * 1000.0

    # Multi-rect cluster & extraction
    t_cluster_start = time.perf_counter()
    clusters = _cluster_above_bboxes_members(above_bboxes, w, h, pad=16, merge_dist=32, max_regions=8)
    t_cluster_end = time.perf_counter()
    cluster_ms = (t_cluster_end - t_cluster_start) * 1000.0

    regions_out, stats_p = _extract_exact_above_regions(above_full, clusters, above_tight_bboxes, w, h)
    exact_crop_ms = stats_p.get("exact_crop_ms", 0.0)
    tobytes_ms = stats_p.get("tobytes_ms", 0.0)
    tight_bbox_ms = get_tight_bbox_collect_ms()

    # Now let's measure individual widget renders directly for this frame
    call_idx = 0
    sum_individual_widgets_ms = 0.0
    for key, ind_cfg in map_above_layout.get("indicators", {}).items():
        if not ind_cfg or not ind_cfg.get("enabled", True):
            continue
        if key in above_capture_keys:
            continue
        widget_calls_count[key] += 1
        
        # Dispatch timing
        t_w0 = time.perf_counter()
        val = frame_kwargs.get(f"{key}_value", 0.0)
        if key == "fit_distance_text":
            val = dist_m
        elif key == "alt_text":
            val = alt_m
        elif key == "iso_text":
            val = iso_val
        elif key == "exposure_text":
            val = exp_val
        elif key == "temp_text":
            val = temp_c
            
        r_img, rx, ry, _ = render_value_indicator(
            canvas_w=w, canvas_h=h, layout=map_above_layout, font_path=font_path,
            key=key, value=val,
            unit=ind_cfg.get("unit", ""), label=ind_cfg.get("title", ""),
        )
        t_w1 = time.perf_counter()
        dur = (t_w1 - t_w0) * 1000.0
        sum_individual_widgets_ms += dur
        
        widget_timing_records.append({
            "frame": frame_idx,
            "widget_key": key,
            "renderer": ind_cfg.get("form", "text"),
            "call_index": call_idx,
            "duration_ms": round(dur, 4),
            "width": r_img.width if r_img else 0,
            "height": r_img.height if r_img else 0,
            "cache_hit_if_known": 1 if dur < 0.1 else 0,
        })
        call_idx += 1

    unattributed = above_compose_ms - sum_individual_widgets_ms
    frame_summary.append({
        "frame": frame_idx,
        "above_compose_ms": above_compose_ms,
        "sum_individual_widgets_ms": sum_individual_widgets_ms,
        "unattributed_ms": unattributed,
        "tight_bbox_ms": tight_bbox_ms,
        "crop_ms": exact_crop_ms,
        "tobytes_ms": tobytes_ms,
    })

# Write widget_calls.csv
with open(OUT_DIR / "widget_calls.csv", "w", newline="", encoding="utf-8") as f:
    writer = csv.writer(f)
    writer.writerow(["widget_key", "renderer_function", "calls_per_frame_avg", "expected_calls_per_frame", "total_calls"])
    for k, cnt in widget_calls_count.items():
        form = map_above_layout["indicators"][k].get("form", "text")
        writer.writerow([k, form, cnt / 600.0, 1.0, cnt])

# Write widget_timing.csv
with open(OUT_DIR / "widget_timing.csv", "w", newline="", encoding="utf-8") as f:
    writer = csv.DictWriter(f, fieldnames=[
        "frame", "widget_key", "renderer", "call_index", "duration_ms", "width", "height", "cache_hit_if_known"
    ])
    writer.writeheader()
    writer.writerows(widget_timing_records)

print("\n--- PER-WIDGET TIMING SUMMARY (600 FRAMES) ---")
per_widget_times = defaultdict(list)
for r in widget_timing_records:
    per_widget_times[r["widget_key"]].append(r["duration_ms"])

for k, vals in per_widget_times.items():
    print(f"  Widget {k:<25}: AVG {np.mean(vals):6.3f} ms | Median {np.median(vals):6.3f} ms | P95 {np.percentile(vals, 95):6.3f} ms")

above_comp_list = [f["above_compose_ms"] for f in frame_summary]
sum_ind_list = [f["sum_individual_widgets_ms"] for f in frame_summary]
unattr_list = [f["unattributed_ms"] for f in frame_summary]

print("\n--- PHASE 4: SUM CONSISTENCY & UNATTRIBUTED MS ---")
print(f"  above_compose_ms:        AVG {np.mean(above_comp_list):6.3f} ms | Median {np.median(above_comp_list):6.3f} ms | P95 {np.percentile(above_comp_list, 95):6.3f} ms")
print(f"  sum_individual_widgets:  AVG {np.mean(sum_ind_list):6.3f} ms | Median {np.median(sum_ind_list):6.3f} ms | P95 {np.percentile(sum_ind_list, 95):6.3f} ms")
print(f"  UNATTRIBUTED GAP:        AVG {np.mean(unattr_list):6.3f} ms | Median {np.median(unattr_list):6.3f} ms | P95 {np.percentile(unattr_list, 95):6.3f} ms")
print("=" * 90)
