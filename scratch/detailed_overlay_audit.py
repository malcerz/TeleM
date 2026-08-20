import time, sys, os, statistics
from pathlib import Path
_root = Path(__file__).resolve().parent.parent
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))
from datetime import datetime, timezone
import numpy as np
from PIL import Image, ImageDraw

from telemetry_fit import process_fit
from src.gui.layout_manager import normalize_layout
from src.telemetry_gpmf_new import gpmf_to_exiftool_json
from src.telemetry_extract import (
    extract_speed_samples, extract_altitude_samples, extract_track_samples,
    extract_iso_samples, extract_exposure_samples, extract_temperature_samples,
    find_gps_anchor
)
from src.ffmpeg.worker_cache import init_worker, WORKER_CACHE
from src.ffmpeg.frame_renderer import render_overlay_frame
from src.indicators.compositor import compose_overlay, _THREAD_CANVAS
from src.indicators.frame_data import prepare_overlay_frame_data

v_file = Path('Video/GX020079.mp4')
fit_file = Path('Video/Morning_Ride.fit')

records = gpmf_to_exiftool_json(str(v_file))[0]
speed_samples = extract_speed_samples(records)
alt_samples = extract_altitude_samples(records)
track_samples = extract_track_samples(records)
iso_samples = extract_iso_samples(records)
exposure_samples = extract_exposure_samples(records)
temp_samples = extract_temperature_samples(records)
anchor_dt = find_gps_anchor(records)
fit_data = process_fit(str(fit_file), video_start_dt=anchor_dt)

layout = normalize_layout(None, 1920, 1080)
total_frames = 1131
target_fps = 29.97

print("=== LAYOUT INDICATORS ===")
for k, v in layout.get("indicators", {}).items():
    if v.get("enabled", True):
        print(f"  {k}: type={v.get('type')}, pos=({v.get('position', {}).get('x')}, {v.get('position', {}).get('y')})")

# Initialize worker cache
init_worker(
    1920, 1080, "", layout, {}, 0.0,
    iso_samples, exposure_samples, temp_samples,
    None, None, None,
    None, None, None, None,
    fit_data,
    fit_data.get("track"),
    anchor_dt, 0.0,
    speed_samples, track_samples, alt_samples,
    target_fps, 1, total_frames,
    cut_regions=[],
    effective_rotation=0,
    hud_bbox=None,
    hud_regions=None,
    hud_rotate_180=False,
)

# Warm up 5 frames
for i in range(5):
    render_overlay_frame(i, anchor_dt, 0.0, speed_samples, track_samples, alt_samples, target_fps)

# 1. Profile full render_overlay_frame for 50 frames
times = []
for i in range(50):
    t0 = time.perf_counter()
    img = render_overlay_frame(i, anchor_dt, 0.0, speed_samples, track_samples, alt_samples, target_fps)
    t1 = time.perf_counter()
    times.append((t1 - t0) * 1000.0)

print(f"\n=== OVERLAY RENDERING (SINGLE THREAD) ===")
print(f"Frames: 50 | Avg: {statistics.mean(times):.2f} ms | Median: {statistics.median(times):.2f} ms | Min: {min(times):.2f} ms | Max: {max(times):.2f} ms")

# 2. Detailed Breakdown of components inside compose_overlay
from src.indicators.frame_data import prepare_overlay_frame_data
from src.indicators.time_block import render_time_block
from src.indicators.time_display import render_time_display
from src.indicators.dispatcher import render_value_indicator
from src.indicators.custom_text import render_custom_text
from src.indicators.rotated_paste import rotated_paste

prep_times = []
ind_times = {k: [] for k in layout.get("indicators", {})}
paste_times = {k: [] for k in layout.get("indicators", {})}
canvas_clear_times = []

for i in range(10, 60):
    t0 = time.perf_counter()
    sample_t = i / target_fps
    from datetime import timedelta
    current_dt = anchor_dt + timedelta(seconds=sample_t)
    data = prepare_overlay_frame_data(
        layout=layout,
        target_dt=current_dt,
        tz_offset_hours=0.0,
        start_dt_utc=anchor_dt,
        speed_samples=speed_samples,
        track_samples=track_samples,
        alt_samples=alt_samples,
        iso_samples=iso_samples,
        exposure_samples=exposure_samples,
        temperature_samples=temp_samples,
        fit_data=fit_data,
        gps_track=fit_data.get("track"),
        total_frames=total_frames,
        current_index=i,
        chart_data=WORKER_CACHE.get("_precomputed_chart_data", {}),
    )
    t_prep = (time.perf_counter() - t0) * 1000.0
    prep_times.append(t_prep)

    # Test individual indicator render times
    for ind_name, cfg in layout.get("indicators", {}).items():
        if not cfg.get("enabled", True):
            continue
        t_i0 = time.perf_counter()
        # render individual indicator
        res = render_value_indicator(
            ind_name, 1920, 1080, layout, "",
            date_text=data["date_text"], time_text=data["time_text"],
            speed_value=data["speed_value"], distance_m=data["distance_m"],
            max_distance_m=data["max_distance_m"], alt_value=data["alt_value"],
            min_alt=data["min_alt"], max_alt=data["max_alt"],
            iso_value=data["iso_value"], exposure_value=data["exposure_value"],
            temp_value=data["temp_value"], indicator_values=data["indicator_values"],
            max_speed_kmh=data["max_speed_kmh"], power_value=data["power_value"],
            atemp_value=data["atemp_value"], hr_value=data["hr_value"],
            cad_value=data["cad_value"], battery_value=data["battery_value"],
            chart_data=data["chart_data"], current_position=data["current_position"],
            extra_indicators=data["extra_indicators"], gps_track=data["gps_track"],
            target_dt=data["target_dt"], start_dt_utc=data["start_dt_utc"],
            elapsed_seconds=data["elapsed_seconds"], avg_speed_kmh=data["avg_speed_kmh"]
        )
        t_i1 = time.perf_counter()
        ind_times[ind_name].append((t_i1 - t_i0) * 1000.0)

print("\n=== PER-INDICATOR RENDER TIME (Avg ms across 50 frames) ===")
total_ind_time = 0
for ind_name, t_list in sorted(ind_times.items(), key=lambda x: statistics.mean(x[1]) if x[1] else 0, reverse=True):
    if t_list:
        avg = statistics.mean(t_list)
        p95 = statistics.quantiles(t_list, n=20)[18] if len(t_list) >= 20 else max(t_list)
        total_ind_time += avg
        ind_type = layout['indicators'][ind_name].get('type', 'unknown')
        print(f"  {ind_name:25s} ({ind_type:12s}): avg={avg:6.2f} ms | p95={p95:6.2f} ms")

print(f"\nTelemetry prep time: avg={statistics.mean(prep_times):.2f} ms")
print(f"Sum of indicators: avg={total_ind_time:.2f} ms")
