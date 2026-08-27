import json
import os
import sys
import time
from pathlib import Path

repo_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(repo_root))

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

print("=" * 90)
print("PROFILING COMPOSITOR REUSE VS NON-REUSE & ABLATION MATRIX (300 frames)")
print("=" * 90)

# Test 1: Full def_layout with reuse_canvas='above' vs reuse_canvas=False
t_reuse_above = []
t_fresh_above = []
t_reuse_below = []
t_fresh_below = []

for frame_idx in range(300):
    t_sec = frame_idx / fps
    d_samp = tm.track_samples
    d_idx = min(len(d_samp) - 1, int(t_sec * 10)) if d_samp else 0
    dist_m = d_samp[d_idx][1] if d_samp else 0.0

    # Below reuse
    t0 = time.perf_counter()
    b_res = compose_overlay(
        canvas_w=w, canvas_h=h, layout=compose_layout, font_path=font_path,
        date_text="2026-08-26", time_text=f"12:{frame_idx//1800:02d}:{(frame_idx//30)%60:02d}",
        speed_value=25.0, distance_m=dist_m, reuse_canvas="below",
    )
    t_reuse_below.append((time.perf_counter() - t0) * 1000.0)

    # Above reuse
    t0 = time.perf_counter()
    a_res = compose_overlay(
        canvas_w=w, canvas_h=h, layout=map_above_layout, font_path=font_path,
        date_text="2026-08-26", time_text=f"12:{frame_idx//1800:02d}:{(frame_idx//30)%60:02d}",
        speed_value=25.0, distance_m=dist_m, _bboxes={}, _tight_bboxes={},
        gpu_capture_keys=above_capture_keys, gpu_capture={}, reuse_canvas="above",
    )
    t_reuse_above.append((time.perf_counter() - t0) * 1000.0)

print(f"CPU BELOW (reuse_canvas='below'): AVG = {np.mean(t_reuse_below):.3f} ms | Median = {np.median(t_reuse_below):.3f} ms")
print(f"CPU ABOVE (reuse_canvas='above'): AVG = {np.mean(t_reuse_above):.3f} ms | Median = {np.median(t_reuse_above):.3f} ms")

# Test 2: Ablation Matrix (Disable individual CPU widgets one by one on 300 frames)
widgets_to_ablate = [
    "time_display",
    "lean_indicator",
    "fit_distance_text",
    "alt_text",
    "iso_text",
    "exposure_text",
    "temp_text",
]

print("\n" + "=" * 90)
print("PHASE 10: REAL ABLATION MATRIX (300 frames each)")
print("=" * 90)

base_total_above = np.mean(t_reuse_above)
base_total_below = np.mean(t_reuse_below)
print(f"BASELINE: Below = {base_total_below:.3f} ms | Above = {base_total_above:.3f} ms | Sum = {base_total_below + base_total_above:.3f} ms\n")

for w_key in widgets_to_ablate:
    # Deep copy layout and disable w_key
    ablated_layout = json.load(open(repo_root / "def_layout.json", encoding="utf-8"))
    if w_key in ablated_layout.get("indicators", {}):
        ablated_layout["indicators"][w_key]["enabled"] = False
    
    c_lay, a_lay, _ = _ordered_map_layout_parts(ablated_layout)
    
    t_b_abl = []
    t_a_abl = []
    for frame_idx in range(300):
        t_sec = frame_idx / fps
        d_idx = min(len(tm.track_samples) - 1, int(t_sec * 10)) if tm.track_samples else 0
        dist_m = tm.track_samples[d_idx][1] if tm.track_samples else 0.0
        
        t0 = time.perf_counter()
        b_res = compose_overlay(
            canvas_w=w, canvas_h=h, layout=c_lay, font_path=font_path,
            date_text="2026-08-26", time_text="12:00:00",
            speed_value=25.0, distance_m=dist_m, reuse_canvas="below",
        )
        t_b_abl.append((time.perf_counter() - t0) * 1000.0)

        t0 = time.perf_counter()
        a_res = compose_overlay(
            canvas_w=w, canvas_h=h, layout=a_lay, font_path=font_path,
            date_text="2026-08-26", time_text="12:00:00",
            speed_value=25.0, distance_m=dist_m, _bboxes={}, _tight_bboxes={},
            gpu_capture_keys=above_capture_keys, gpu_capture={}, reuse_canvas="above",
        )
        t_a_abl.append((time.perf_counter() - t0) * 1000.0)
    
    mean_b = np.mean(t_b_abl)
    mean_a = np.mean(t_a_abl)
    delta_b = base_total_below - mean_b
    delta_a = base_total_above - mean_a
    total_delta = (base_total_below + base_total_above) - (mean_b + mean_a)
    print(f"Widget OFF: {w_key:<20} | Below: {mean_b:.3f} ms (d {delta_b:+.3f} ms) | Above: {mean_a:.3f} ms (d {delta_a:+.3f} ms) | Total d: {total_delta:+.3f} ms")
