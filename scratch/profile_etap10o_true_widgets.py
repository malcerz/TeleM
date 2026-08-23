import os
import sys
import copy
import json
import time
import numpy as np
from pathlib import Path
from datetime import datetime, timezone, timedelta
from collections import defaultdict

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.gui.telemetry_manager import TelemetryDataManager
from src.indicators.frame_data import prepare_overlay_frame_data
import src.indicators.compositor as compositor
from src.indicators.compositor import compose_overlay
import src.indicators.dispatcher as dispatcher
from src.ffmpeg.amd_native_exporter import _ordered_map_layout_parts
from src.telemetry_extract import (
    extract_speed_samples, extract_altitude_samples, extract_track_samples,
    extract_iso_samples, extract_exposure_samples, extract_temperature_samples,
    ensure_records_list, extract_gps_track,
    smooth_speed_samples, interpolate_value, get_rotation_from_metadata,
    get_container_rotation, find_metadata_json, load_json_with_fallback,
    smooth_speed_values, extract_accelerometer_samples, extract_gyroscope_samples,
)

root = Path(__file__).resolve().parents[1]
video_path = root / "Video" / "GX010115.MP4"
json_path = root / "Video" / "GX010115.json"
fit_path = root / "Video" / "Jazda_na_rowerze_w_porze_lunchu.fit"
layout_path = root / "presets" / "cycling_dashboard_v10.json"

with open(layout_path, "r", encoding="utf-8") as f:
    v10_layout = json.load(f)

with open(json_path, "r", encoding="utf-8") as f:
    meta = json.load(f)
records = ensure_records_list(meta)

telemetry = TelemetryDataManager(
    extract_speed_fn=extract_speed_samples,
    extract_altitude_fn=extract_altitude_samples,
    extract_track_fn=extract_track_samples,
    extract_iso_fn=extract_iso_samples,
    extract_exposure_fn=extract_exposure_samples,
    extract_temperature_fn=extract_temperature_samples,
    smooth_fn=smooth_speed_samples,
    interpolate_fn=interpolate_value,
    get_rotation_meta_fn=get_rotation_from_metadata,
    get_container_rotation_fn=get_container_rotation,
    find_meta_json_fn=find_metadata_json,
    find_meta_json_write_fn=lambda p: p.with_suffix(".json"),
    load_telemetry_fn=lambda *a: None,
    ensure_records_fn=ensure_records_list,
    load_json_fallback_fn=load_json_with_fallback,
    write_records_fn=lambda p, r: None,
    extract_samples_exiftool_fn=lambda f: [],
    extract_altitude_exiftool_fn=lambda f: [],
    extract_gps_track_fn=extract_gps_track,
    find_gps_anchor_fn=lambda r: None,
    smooth_values_fn=smooth_speed_values,
    extract_accelerometer_fn=extract_accelerometer_samples,
    extract_gyroscope_fn=extract_gyroscope_samples,
)

telemetry.load_gpmf_records(records)
telemetry.load_gps_track(records)
telemetry.load_fit(video_path, telemetry.start_dt_utc, manual_path=fit_path)

start_dt = telemetry.start_dt_utc
canvas_w, canvas_h = 1280, 720
fps = 60.0
total_frames = 120

below_layout, above_layout, after_keys = _ordered_map_layout_parts(v10_layout)

frames_kw = []
for i in range(total_frames):
    dt = start_dt + timedelta(seconds=i / fps)
    kw = prepare_overlay_frame_data(
        target_dt=dt, start_dt_utc=start_dt, tz_offset_hours=2.0, layout=v10_layout,
        speed_samples=telemetry.speed_samples, track_samples=telemetry.track_samples,
        alt_samples=telemetry.alt_samples, iso_samples=telemetry.iso_samples,
        exposure_samples=telemetry.exposure_samples, temperature_samples=telemetry.temperature_samples,
        fit_data=telemetry.fit_data, gps_track=telemetry.get_gps_track_for_source("fit"),
        resolve_cache_value=lambda k, src, d, ind=None: telemetry.resolve_value(k, d, source=src),
    )
    frames_kw.append(kw)

# Timing collectors
render_timings = defaultdict(list)
paste_timings = defaultdict(list)
total_timings = defaultdict(list)
below_compose_list = []
above_compose_list = []

# Wrap functions in compositor and dispatcher
orig_render_val = compositor.render_value_indicator
orig_render_time = compositor.render_time_display
orig_paste = compositor.rotated_paste

def hooked_render_val(*args, **kwargs):
    key = args[4] if len(args) > 4 else kwargs.get("key", "unknown")
    t0 = time.perf_counter()
    res = orig_render_val(*args, **kwargs)
    t1 = time.perf_counter()
    render_timings[key].append((t1 - t0) * 1000.0)
    return res

def hooked_render_time(*args, **kwargs):
    t0 = time.perf_counter()
    res = orig_render_time(*args, **kwargs)
    t1 = time.perf_counter()
    render_timings["time_display"].append((t1 - t0) * 1000.0)
    return res

def hooked_paste(target, source, cx, cy, rotation, *args, **kwargs):
    cache_key = kwargs.get("cache_key", "unknown")
    t0 = time.perf_counter()
    res = orig_paste(target, source, cx, cy, rotation, *args, **kwargs)
    t1 = time.perf_counter()
    paste_timings[cache_key].append((t1 - t0) * 1000.0)
    return res

compositor.render_value_indicator = hooked_render_val
compositor.render_time_display = hooked_render_time
compositor.rotated_paste = hooked_paste

# Run 120 frames production loop
for idx in range(total_frames):
    kw = frames_kw[idx]
    
    # BELOW
    b_bb = {}
    tb0 = time.perf_counter()
    b_img = compose_overlay(canvas_w, canvas_h, below_layout, "", _bboxes=b_bb, reuse_canvas="below", **kw)
    tb1 = time.perf_counter()
    below_compose_list.append((tb1 - tb0) * 1000.0)
    
    # ABOVE
    a_bb = {}
    ta0 = time.perf_counter()
    a_img = compose_overlay(canvas_w, canvas_h, above_layout, "", _bboxes=a_bb, reuse_canvas="above", **kw)
    ta1 = time.perf_counter()
    above_compose_list.append((ta1 - ta0) * 1000.0)

# Unhook
compositor.render_value_indicator = orig_render_val
compositor.render_time_display = orig_render_time
compositor.rotated_paste = orig_paste

def stats(arr):
    if not arr:
        return 0.0, 0.0, 0.0
    a = np.array(arr)
    return float(np.mean(a)), float(np.median(a)), float(np.percentile(a, 95))

print("\n" + "="*90)
print("ACCURATE FRESH PER-WIDGET PROFILE — BELOW (120 frames)")
print("="*90)
below_keys = list(below_layout["indicators"].keys())
for k in below_keys:
    r_m, r_med, r_p95 = stats(render_timings.get(k, []))
    p_m, p_med, p_p95 = stats(paste_timings.get(k, []))
    tot_arr = [r + p for r, p in zip(render_timings.get(k, [0]*120), paste_timings.get(k, [0]*120))]
    t_m, t_med, t_p95 = stats(tot_arr)
    print(f"{k:<25} | Render: {r_m:.3f} ms (med: {r_med:.3f}, p95: {r_p95:.3f}) | Paste: {p_m:.3f} ms (med: {p_med:.3f}) | TOTAL: {t_m:.3f} ms (med: {t_med:.3f}, p95: {t_p95:.3f})")

print("\n" + "="*90)
print("ACCURATE FRESH PER-WIDGET PROFILE — ABOVE (120 frames)")
print("="*90)
above_keys = list(above_layout["indicators"].keys())
for k in above_keys:
    r_m, r_med, r_p95 = stats(render_timings.get(k, []))
    p_m, p_med, p_p95 = stats(paste_timings.get(k, []))
    tot_arr = [r + p for r, p in zip(render_timings.get(k, [0]*120), paste_timings.get(k, [0]*120))]
    t_m, t_med, t_p95 = stats(tot_arr)
    print(f"{k:<25} | Render: {r_m:.3f} ms (med: {r_med:.3f}, p95: {r_p95:.3f}) | Paste: {p_m:.3f} ms (med: {p_med:.3f}) | TOTAL: {t_m:.3f} ms (med: {t_med:.3f}, p95: {t_p95:.3f})")

b_tot_m, b_tot_med, b_tot_p95 = stats(below_compose_list)
a_tot_m, a_tot_med, a_tot_p95 = stats(above_compose_list)

sum_below = sum(stats([r + p for r, p in zip(render_timings.get(k, [0]*120), paste_timings.get(k, [0]*120))])[0] for k in below_keys)
sum_above = sum(stats([r + p for r, p in zip(render_timings.get(k, [0]*120), paste_timings.get(k, [0]*120))])[0] for k in above_keys)

print("\n" + "="*90)
print("COMPOSE TOTALS & RESIDUALS")
print("="*90)
print(f"BELOW compose_overlay : mean {b_tot_m:.3f} ms (median {b_tot_med:.3f} ms, p95 {b_tot_p95:.3f} ms) | SUM widgets: {sum_below:.3f} ms | Residual: {max(0.0, b_tot_m - sum_below):.3f} ms")
print(f"ABOVE compose_overlay : mean {a_tot_m:.3f} ms (median {a_tot_med:.3f} ms, p95 {a_tot_p95:.3f} ms) | SUM widgets: {sum_above:.3f} ms | Residual: {max(0.0, a_tot_m - sum_above):.3f} ms")

out_data = {
    "below_widgets": {k: {"render": stats(render_timings[k]), "paste": stats(paste_timings[k]), "total": stats([r+p for r,p in zip(render_timings[k], paste_timings[k])])} for k in below_keys},
    "above_widgets": {k: {"render": stats(render_timings[k]), "paste": stats(paste_timings[k]), "total": stats([r+p for r,p in zip(render_timings[k], paste_timings[k])])} for k in above_keys},
    "below_compose": (b_tot_m, b_tot_med, b_tot_p95),
    "above_compose": (a_tot_m, a_tot_med, a_tot_p95),
    "sum_below": sum_below,
    "sum_above": sum_above,
    "below_residual": max(0.0, b_tot_m - sum_below),
    "above_residual": max(0.0, a_tot_m - sum_above),
}

with open(root / "scratch" / "profile_etap10o_accurate.json", "w", encoding="utf-8") as f:
    json.dump(out_data, f, indent=2)
print("\nWrote scratch/profile_etap10o_accurate.json")
