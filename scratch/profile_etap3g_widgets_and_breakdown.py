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
from src.indicators.dispatcher import render_value_indicator
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

print("=" * 90)
print("PHASE 5: RUNTIME INVENTORY OF ACTIVE CPU & GPU WIDGETS (def_layout.json)")
print("=" * 90)

print("\n1. CPU BELOW (compose_layout):")
for k, cfg in compose_layout.get("indicators", {}).items():
    if cfg.get("enabled", True):
        print(f"  - {k:<25} (form={cfg.get('form')}, source={cfg.get('source', 'none')})")

print("\n2. CPU ABOVE (map_above_layout):")
for k, cfg in map_above_layout.get("indicators", {}).items():
    if cfg.get("enabled", True):
        is_gpu = k in gpu_chart_keys or k == gpu_gauge_key
        print(f"  - {k:<25} (form={cfg.get('form')}, source={cfg.get('source', 'none')}) -> {'GPU CAPTURED' if is_gpu else 'CPU RENDERED'}")

print("\n3. GPU NATIVE LAYERS:")
print(f"  - Track-Up Map (GPU resample & rotate)")
print(f"  - HR AFTER-MAP chart ({gpu_chart_keys})")
print(f"  - Cadence AFTER-MAP chart ({gpu_chart_keys})")
print(f"  - Speed Gauge AFTER-MAP ({gpu_gauge_key})")

print("\n" + "=" * 90)
print("PHASE 6 & 7 & 8: PER-WIDGET TIMING & COMPOSITOR BREAKDOWN (1000 frames)")
print("=" * 90)

# Track per-widget render times
widget_timings = {}
below_total_times = []
above_total_times = []

above_capture_keys = gpu_chart_keys | {gpu_gauge_key}

for frame_idx in range(1000):
    t_sec = frame_idx / fps
    d_samp = tm.track_samples
    d_idx = min(len(d_samp) - 1, int(t_sec * 10)) if d_samp else 0
    dist_m = d_samp[d_idx][1] if d_samp else 0.0
    
    # 1. Profile CPU BELOW
    t_b0 = time.perf_counter()
    below_bboxes = {}
    below_full = compose_overlay(
        canvas_w=w, canvas_h=h, layout=compose_layout, font_path=font_path,
        date_text="2026-08-26", time_text=f"12:{frame_idx//1800:02d}:{(frame_idx//30)%60:02d}",
        speed_value=25.0 + np.sin(frame_idx / 20.0) * 10.0, distance_m=dist_m,
        _bboxes=below_bboxes, _tight_bboxes={}, gpu_capture_keys=above_capture_keys,
        gpu_capture={}, reuse_canvas=False,
    )
    t_bel = (time.perf_counter() - t_b0) * 1000.0
    below_total_times.append(t_bel)

    # 2. Profile CPU ABOVE
    t_a0 = time.perf_counter()
    above_bboxes = {}
    above_tight_bboxes = {}
    above_full = compose_overlay(
        canvas_w=w, canvas_h=h, layout=map_above_layout, font_path=font_path,
        date_text="2026-08-26", time_text=f"12:{frame_idx//1800:02d}:{(frame_idx//30)%60:02d}",
        speed_value=25.0 + np.sin(frame_idx / 20.0) * 10.0, distance_m=dist_m,
        _bboxes=above_bboxes, _tight_bboxes=above_tight_bboxes, gpu_capture_keys=above_capture_keys,
        gpu_capture={}, reuse_canvas=False,
    )
    t_abv = (time.perf_counter() - t_a0) * 1000.0
    above_total_times.append(t_abv)

print(f"{'Phase / Stage':<30} {'AVG (ms)':<12} {'Median (ms)':<12} {'P95 (ms)':<12}")
print("-" * 75)
print(f"{'CPU BELOW compose_overlay':<30} {np.mean(below_total_times):<12.3f} {np.median(below_total_times):<12.3f} {np.percentile(below_total_times, 95):<12.3f}")
print(f"{'CPU ABOVE compose_overlay':<30} {np.mean(above_total_times):<12.3f} {np.median(above_total_times):<12.3f} {np.percentile(above_total_times, 95):<12.3f}")

# Now profile individual active CPU widgets directly
print("\n" + "=" * 90)
print("INDIVIDUAL ACTIVE CPU WIDGET PROFILE (1000 calls each)")
print("=" * 90)

active_widgets_to_profile = [
    # BELOW
    ("time_display", compose_layout.get("indicators", {}).get("time_display"), "time_display", 0.0),
    # ABOVE
    ("lean_indicator (CPU)", map_above_layout.get("indicators", {}).get("lean_indicator"), "lean", 12.5),
    ("fit_distance_text", map_above_layout.get("indicators", {}).get("fit_distance_text"), "bar", 12.3),
    ("alt_text", map_above_layout.get("indicators", {}).get("alt_text"), "bar", 245.0),
    ("iso_text", map_above_layout.get("indicators", {}).get("iso_text"), "text", 200),
    ("exposure_text", map_above_layout.get("indicators", {}).get("exposure_text"), "text", -0.3),
    ("temp_text", map_above_layout.get("indicators", {}).get("temp_text"), "text", 24.5),
]

ind_results = {}
for name, cfg, form, val in active_widgets_to_profile:
    if cfg is None:
        continue
    t_ind = []
    min_dim = 2160
    for i in range(1000):
        t0 = time.perf_counter()
        res = render_value_indicator(
            canvas_w=w,
            canvas_h=h,
            layout=layout,
            font_path=font_path,
            key=name.split()[0],
            value=val,
            unit=cfg.get("unit", ""),
            label=cfg.get("label", name),
            cfg_override=cfg,
            formatted_val=f"{val} {cfg.get('unit','')}".strip()
        )
        img = res[0]
        t_ind.append((time.perf_counter() - t0) * 1000.0)
    ind_results[name] = t_ind
    print(f"{name:<28} AVG: {np.mean(t_ind):.4f} ms | Median: {np.median(t_ind):.4f} ms | P95: {np.percentile(t_ind, 95):.4f} ms")

print("\n" + "=" * 90)
print("PHASE 8: COMPOSITOR UNATTRIBUTED OVERHEAD")
print("=" * 90)
sum_above_widgets = sum(np.mean(ind_results[k]) for k in ind_results if "time_display" not in k)
unattributed_above = np.mean(above_total_times) - sum_above_widgets
print(f"Sum of active CPU ABOVE widgets: {sum_above_widgets:.3f} ms")
print(f"CPU ABOVE compose_overlay total:  {np.mean(above_total_times):.3f} ms")
print(f"Unattributed ABOVE compositor:    {unattributed_above:.3f} ms")
