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
from src.ffmpeg.amd_native_exporter import (
    _ordered_map_layout_parts,
    _rect_union,
    _clip_rect,
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
print("PHASE 25: 2000-FRAME BIT-FOR-BIT EXACT PARITY TEST (RETAINED HUD + FINE DIRTY)")
print("=" * 90)

# Simulate GPU Retained HUD canvas (RGBA)
retained_gpu_hud = Image.new("RGBA", (w, h), (0, 0, 0, 0))
prev_dirty_rects = []
prev_widget_dirty = {}

max_diff_global = 0
different_pixels_global = 0
total_bytes_fine = 0
total_bytes_full = 0

frames_to_test = 2000

t_start = time.perf_counter()
for frame_idx in range(frames_to_test):
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
    
    # Ground Truth CPU Reference Canvas for this frame
    ground_truth_canvas = compose_overlay(
        canvas_w=w, canvas_h=h, layout=map_above_layout, font_path=font_path,
        date_text="2026-08-26", time_text=f"12:{frame_idx//1800:02d}:{(frame_idx//30)%60:02d}",
        speed_value=25.0 + np.sin(frame_idx / 20.0) * 10.0, distance_m=dist_m,
        alt_value=alt_m, temp_value=temp_c, iso_value=iso_val, exposure_value=exp_val,
        _bboxes=above_bboxes, _tight_bboxes=above_tight_bboxes,
        gpu_capture_keys=above_capture_keys, gpu_capture={}, reuse_canvas="above",
    )

    if frame_idx == 0:
        # Frame 0: Full Initial Retained Upload
        retained_gpu_hud.paste(ground_truth_canvas, (0, 0))
        prev_dirty_rects = []
        prev_widget_dirty = {}
        for k, box in above_bboxes.items():
            prev_widget_dirty[k] = box
            total_bytes_full += box[2] * box[3] * 4
            total_bytes_fine += box[2] * box[3] * 4
    else:
        # Frame N >= 1: Retained Fine-Grained Dynamic Dirty Updates
        # 1. Clear previous fine dirty regions on retained GPU HUD
        for bx, by, bw, bh in prev_dirty_rects:
            retained_gpu_hud.paste((0, 0, 0, 0), (bx, by, bx + bw, by + bh))
        
        current_dirty_rects = []
        for k, box in above_bboxes.items():
            full_b = box[2] * box[3] * 4
            total_bytes_full += full_b
            
            # Determine fine dynamic dirty bbox
            tight = above_tight_bboxes.get(k)
            if isinstance(tight, dict) and "bbox" in tight:
                curr_dyn = tight["bbox"]
            elif isinstance(tight, (tuple, list)):
                curr_dyn = tuple(tight)
            else:
                curr_dyn = box
            prev_dyn = prev_widget_dirty.get(k, curr_dyn)
            
            # Union of previous and current dynamic dirty regions
            union_box = _rect_union(prev_dyn, curr_dyn)
            clipped = _clip_rect(union_box, w, h, pad=4)
            if clipped is not None:
                cx, cy, cw, ch = clipped
                if cw > 0 and ch > 0:
                    current_dirty_rects.append(clipped)
                    # Extract patch from current ground truth canvas and blend into retained GPU HUD
                    patch = ground_truth_canvas.crop((cx, cy, cx + cw, cy + ch))
                    retained_gpu_hud.alpha_composite(patch, (cx, cy))
                    total_bytes_fine += cw * ch * 4
            
            prev_widget_dirty[k] = curr_dyn
        
        prev_dirty_rects = current_dirty_rects

    # Verify Bit-For-Bit Parity against Ground Truth
    gt_arr = np.asarray(ground_truth_canvas)
    ret_arr = np.asarray(retained_gpu_hud)
    diff = np.abs(gt_arr.astype(np.int32) - ret_arr.astype(np.int32))
    md = int(np.max(diff))
    if md > max_diff_global:
        max_diff_global = md
    different_pixels_global += int(np.sum(diff > 0) // 4)

    if (frame_idx + 1) % 500 == 0:
        print(f"  Frame {frame_idx + 1:4d} / {frames_to_test}: MaxDiff = {max_diff_global}, DiffPx = {different_pixels_global}")

elapsed = time.perf_counter() - t_start
avg_full_mb = (total_bytes_full / frames_to_test) / (1024 * 1024)
avg_fine_kb = (total_bytes_fine / frames_to_test) / 1024
red_pct = (1.0 - (total_bytes_fine / total_bytes_full)) * 100.0

print("\n" + "=" * 90)
print(f"2000-FRAME PARITY VERIFICATION SUMMARY (elapsed {elapsed:.2f} s):")
print(f"  MaxDiff:                {max_diff_global}")
print(f"  DifferentPixels:        {different_pixels_global}")
print(f"  Full Multi-Rect Volume: {avg_full_mb:.3f} MB / frame")
print(f"  Fine Dirty Volume:      {avg_fine_kb:.1f} KB / frame")
print(f"  Byte Reduction:         {red_pct:.2f} %")
if max_diff_global == 0 and different_pixels_global == 0:
    print("  RESULT: 100% BIT-FOR-BIT EXACT PARITY PASS (ZERO GHOSTING, ZERO STALE PIXELS)!")
else:
    print("  RESULT: FAILED PARITY")
print("=" * 90)
