import sys
import json
import time
from pathlib import Path
from collections import defaultdict
import statistics

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.gui.telemetry_manager import TelemetryDataManager
from src.indicators.frame_data import prepare_overlay_frame_data
import src.indicators.chart as chart
import src.indicators.chart_utils as chart_utils
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
    layout = json.load(f)

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

with open(json_path, "r", encoding="utf-8") as f:
    meta = json.load(f)
records = ensure_records_list(meta)
telemetry.load_gpmf_records(records)
telemetry.load_gps_track(records)
telemetry.load_fit(video_path, telemetry.start_dt_utc, manual_path=fit_path)

# Let's instrument chart._render_chart_indicator sub-operations
timings = defaultdict(lambda: defaultdict(list))

orig_render_chart_indicator = chart._render_chart_indicator

# We can instrument internal calls or time each phase
from PIL import Image, ImageDraw

def instrumented_render(
    canvas_w, canvas_h, layout, font_path, key, value, unit, label,
    cfg, min_dim, outline, fs, font, val_min, val_max, ticks, thickness, size_px, ss,
    history_data=None, current_position=None, formatted_val=None,
    split_mode=False, target_dt=None,
):
    t_start = time.perf_counter()
    
    # 1. History extraction
    t0 = time.perf_counter()
    time_labels = None
    chart_vals = None
    timestamps = None
    if isinstance(history_data, dict):
        chart_vals = history_data.get("values", [])
        time_labels = history_data.get("time_labels")
        timestamps = history_data.get("timestamps")
    elif isinstance(history_data, list):
        chart_vals = history_data
        timestamps = getattr(history_data, "timestamps", None)
    if not chart_vals:
        chart_vals = [value, value]
    chart_w = size_px
    chart_h = max(40, int(chart_w * 0.4))
    t1 = time.perf_counter()
    timings[key]["1_history_prep"].append((t1 - t0) * 1000.0)
    
    # 2. Header & Static Cache Lookup
    t0 = time.perf_counter()
    # Call the original to get ground truth, but measure sub-steps
    res = orig_render_chart_indicator(
        canvas_w, canvas_h, layout, font_path, key, value, unit, label,
        cfg, min_dim, outline, fs, font, val_min, val_max, ticks, thickness, size_px, ss,
        history_data=history_data, current_position=current_position, formatted_val=formatted_val,
        split_mode=split_mode, target_dt=target_dt,
    )
    t_end = time.perf_counter()
    timings[key]["total"].append((t_end - t_start) * 1000.0)
    return res

chart._render_chart_indicator = instrumented_render

print("Running 120-frame microprofile...")
start_dt = telemetry.start_dt_utc
from datetime import timedelta

# Warmup 10 frames
for i in range(10):
    dt = start_dt + timedelta(seconds=i / 60.0)
    prepare_overlay_frame_data(
        target_dt=dt,
        start_dt_utc=start_dt,
        tz_offset_hours=2.0,
        layout=layout,
        speed_samples=telemetry.speed_samples,
        track_samples=telemetry.track_samples,
        alt_samples=telemetry.alt_samples,
        iso_samples=telemetry.iso_samples,
        exposure_samples=telemetry.exposure_samples,
        temperature_samples=telemetry.temperature_samples,
        fit_data=telemetry.fit_data,
        gps_track=telemetry.get_gps_track_for_source("fit"),
        resolve_cache_value=lambda k, src, d, ind=None: telemetry.resolve_value(k, d, source=src),
    )

timings.clear()

# Measure steady-state frames 11-120 (110 frames)
for i in range(10, 120):
    dt = start_dt + timedelta(seconds=i / 60.0)
    prepare_overlay_frame_data(
        target_dt=dt,
        start_dt_utc=start_dt,
        tz_offset_hours=2.0,
        layout=layout,
        speed_samples=telemetry.speed_samples,
        track_samples=telemetry.track_samples,
        alt_samples=telemetry.alt_samples,
        iso_samples=telemetry.iso_samples,
        exposure_samples=telemetry.exposure_samples,
        temperature_samples=telemetry.temperature_samples,
        fit_data=telemetry.fit_data,
        gps_track=telemetry.get_gps_track_for_source("fit"),
        resolve_cache_value=lambda k, src, d, ind=None: telemetry.resolve_value(k, d, source=src),
    )

for k in ["fit_heart_rate_text", "fit_cadence_text"]:
    tot_list = timings[k]["total"]
    if tot_list:
        print(f"\n--- {k} (Steady State {len(tot_list)} frames) ---")
        print(f"  Mean:   {statistics.fmean(tot_list):.3f} ms")
        print(f"  Median: {statistics.median(tot_list):.3f} ms")
        print(f"  Min:    {min(tot_list):.3f} ms")
        print(f"  Max:    {max(tot_list):.3f} ms")
