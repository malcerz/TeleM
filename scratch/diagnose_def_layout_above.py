import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.gui.telemetry_manager import TelemetryDataManager
from src.telemetry_processed_cache import read_processed_cache, apply_processed_cache
from src.telemetry_extract import (
    get_rotation_from_metadata,
    load_json_with_fallback,
    ensure_records_list,
)
from src.indicators.compositor import compose_overlay
from src.ffmpeg.amd_native_exporter import _amd_layout_roles

VIDEO = Path("Video/GX030120.MP4")
FIT = Path("Video/Jazda_na_rowerze_w_porze_lunchu.fit")

layout = json.load(open("def_layout.json", encoding="utf-8"))
semantic_layout, compose_layout, map_above_layout, map_after_keys = _amd_layout_roles(layout, True)

print("=" * 80)
print(f"MAP AFTER KEYS in def_layout.json: {map_after_keys}")
print("=" * 80)
print("INDICATORS IN map_above_layout:")
for k, cfg in map_above_layout.get("indicators", {}).items():
    print(f"  {k:<25} enabled={cfg.get('enabled')}, form={cfg.get('form')}")

tm = TelemetryDataManager()
processed = read_processed_cache(VIDEO)
if processed:
    apply_processed_cache(tm, processed)
else:
    tm.load_gpmf_from_exiftool(VIDEO)
tm.load_fit(VIDEO, start_dt=tm.start_dt_utc, manual_path=FIT)

# Simulate 300 frames of above_compose and measure each widget individually
from src.indicators.dispatcher import render_value_indicator
from src.indicators.time_display import render_time_display
from src.indicators.compositor import indicator_font_path, rotated_paste

w, h = 3840, 2160
font_path = "arial.ttf"

print("\n" + "=" * 80)
print("PROFILING INDIVIDUAL WIDGET RENDERING COSTS (300 frames):")
print("=" * 80)

widget_times = {}
widget_counts = {}

# Test frame kwargs for first 300 frames
from src.telemetry_precompute import precompute_telemetry_cache
tc = precompute_telemetry_cache(
    tm, num_frames=300, target_fps=30000.0/1001.0, duration_s=300/(30000.0/1001.0),
    layout=semantic_layout, video_width=w, video_height=h
)

for idx in range(300):
    f_kw = tc.lookup(idx)

    # Let's render above_full with GPU capture keys active:
    gpu_capture_keys = {"fit_heart_rate_text", "fit_cadence_text", "speed_text"}
    gpu_capture = {}
    above_bboxes = {}
    above_tight_bboxes = {}

    t0 = time.perf_counter()
    above_img = compose_overlay(
        canvas_w=w,
        canvas_h=h,
        layout=map_above_layout,
        font_path=font_path,
        _bboxes=above_bboxes,
        _tight_bboxes=above_tight_bboxes,
        gpu_capture_keys=gpu_capture_keys,
        gpu_capture=gpu_capture,
        split_chart_keys=gpu_capture_keys,
        reuse_canvas="above",
        **f_kw
    )
    t_tot = (time.perf_counter() - t0) * 1000.0

    if "above_total" not in widget_times:
        widget_times["above_total"] = []
    widget_times["above_total"].append(t_tot)

print(f"Total above_compose time across 300 frames: avg = {sum(widget_times['above_total'])/len(widget_times['above_total']):.3f} ms")
print(f"Captured to GPU: {list(gpu_capture.keys())}")
print(f"Rendered in CPU ABOVE: {list(above_bboxes.keys())}")
