import csv
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
from src.indicators.compositor import compose_overlay
from src.ffmpeg.amd_native_exporter import _ordered_map_layout_parts

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

OUT_DIR = repo_root / "Raporty" / "AMD_ETAP_3H"
OUT_DIR.mkdir(parents=True, exist_ok=True)
STATS_CSV = OUT_DIR / "dirty_stats.csv"

print("=" * 90)
print("PHASE 2 & 3 & 4: CURRENT ABOVE BREAKDOWN & 500-FRAME PIXEL VARIABILITY")
print("=" * 90)

prev_canvas = None
dirty_stats_rows = []

widget_full_areas = {
    "fit_distance_text": [],
    "alt_text": [],
    "lean_indicator": [],
    "text_indicators": [],
}
widget_changed_areas = {
    "fit_distance_text": [],
    "alt_text": [],
    "lean_indicator": [],
    "text_indicators": [],
}

# 500 frames probe
for frame_idx in range(500):
    t_sec = frame_idx / fps
    d_samp = tm.track_samples
    d_idx = min(len(d_samp) - 1, int(t_sec * 10)) if d_samp else 0
    dist_m = d_samp[d_idx][1] if d_samp else 0.0

    above_bboxes = {}
    above_tight_bboxes = {}
    
    current_canvas = compose_overlay(
        canvas_w=w, canvas_h=h, layout=map_above_layout, font_path=font_path,
        date_text="2026-08-26", time_text=f"12:{frame_idx//1800:02d}:{(frame_idx//30)%60:02d}",
        speed_value=25.0 + np.sin(frame_idx / 20.0) * 10.0, distance_m=dist_m,
        _bboxes=above_bboxes, _tight_bboxes=above_tight_bboxes,
        gpu_capture_keys=above_capture_keys, gpu_capture={}, reuse_canvas=False,
    )
    
    if prev_canvas is not None:
        # Measure actual pixel differences per widget ROI
        curr_arr = np.asarray(current_canvas)
        prev_arr = np.asarray(prev_canvas)
        diff_mask = np.any(curr_arr != prev_arr, axis=-1)  # 2D boolean mask (H, W)

        for w_key, box in above_bboxes.items():
            bx, by, bw, bh = box
            full_area = bw * bh
            full_bytes = full_area * 4
            
            # Slice diff mask in widget box
            sub_mask = diff_mask[by:by+bh, bx:bx+bw]
            changed_pixels = int(np.sum(sub_mask))
            
            if changed_pixels > 0:
                rows = np.any(sub_mask, axis=1)
                cols = np.any(sub_mask, axis=0)
                rmin, rmax = np.where(rows)[0][[0, -1]]
                cmin, cmax = np.where(cols)[0][[0, -1]]
                dyn_w = cmax - cmin + 1
                dyn_h = rmax - rmin + 1
                dyn_area = dyn_w * dyn_h
            else:
                dyn_area = 0
                dyn_w, dyn_h = 0, 0
            
            dyn_bytes = dyn_area * 4
            
            group_key = "text_indicators" if w_key in ("iso_text", "exposure_text", "temp_text") else w_key
            if group_key in widget_full_areas:
                widget_full_areas[group_key].append(full_area)
                widget_changed_areas[group_key].append(dyn_area)
            
            dirty_stats_rows.append({
                "frame": frame_idx,
                "widget": w_key,
                "full_bbox_area": full_area,
                "dynamic_bbox_area": dyn_area,
                "bytes": dyn_bytes,
                "changed": changed_pixels > 0,
                "fallback_reason": "none",
            })
            
    prev_canvas = current_canvas

print(f"{'Widget Cluster':<25} {'Full BBox (px)':<18} {'Full (MB)':<12} {'Changed ROI (px)':<18} {'Changed (KB)':<14} {'Reduction':<12}")
print("-" * 105)

total_full_b = 0
total_dyn_b = 0
for k in widget_full_areas:
    if widget_full_areas[k]:
        f_avg = np.mean(widget_full_areas[k])
        d_avg = np.mean(widget_changed_areas[k])
        f_mb = f_avg * 4 / (1024 * 1024)
        d_kb = d_avg * 4 / 1024
        red = (1.0 - (d_avg / f_avg if f_avg > 0 else 0)) * 100.0
        total_full_b += f_avg * 4
        total_dyn_b += d_avg * 4
        print(f"{k:<25} {f_avg:<18.0f} {f_mb:<12.3f} {d_avg:<18.0f} {d_kb:<14.1f} {red:<12.1f}%")

total_red = (1.0 - total_dyn_b / total_full_b) * 100.0
print("-" * 105)
print(f"{'TOTAL CPU ABOVE':<25} {total_full_b/4:<18.0f} {total_full_b/1024/1024:<12.3f} {total_dyn_b/4:<18.0f} {total_dyn_b/1024:<14.1f} {total_red:<12.1f}%")

with open(STATS_CSV, "w", newline="", encoding="utf-8") as f:
    writer = csv.DictWriter(f, fieldnames=[
        "frame", "widget", "full_bbox_area", "dynamic_bbox_area", "bytes", "changed", "fallback_reason"
    ])
    writer.writeheader()
    writer.writerows(dirty_stats_rows)

print(f"\nWritten {len(dirty_stats_rows)} dirty stats rows to {STATS_CSV}")
