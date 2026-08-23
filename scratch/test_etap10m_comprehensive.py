import sys
import json
import time
from pathlib import Path
from datetime import timedelta
import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.gui.telemetry_manager import TelemetryDataManager
from src.indicators.frame_data import prepare_overlay_frame_data
import src.indicators.compositor as compositor
import src.indicators.chart as chart
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

start_dt = telemetry.start_dt_utc

print("=" * 75)
print("1. PIXEL PARITY & RANDOM-ACCESS PARITY (Direct Seek vs Sequential)")
print("=" * 75)

test_seconds = [7.0, 60.0, 147.0, 300.0, 585.0]

for sec in test_seconds:
    # A: Fresh / direct seek render
    chart._FINAL_STATIC_CHART_CACHE.clear()
    chart._DOT_TILES_CACHE.clear()
    dt = start_dt + timedelta(seconds=sec)
    kwargs_direct = prepare_overlay_frame_data(
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
    img_direct = compositor.compose_overlay(1280, 720, layout, "", reuse_canvas=False, **kwargs_direct)
    
    # B: Warm / sequential seek render
    kwargs_seq = prepare_overlay_frame_data(
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
    img_seq = compositor.compose_overlay(1280, 720, layout, "", reuse_canvas=False, **kwargs_seq)
    
    arr_direct = np.array(img_direct)
    arr_seq = np.array(img_seq)
    diff = np.abs(arr_direct.astype(int) - arr_seq.astype(int))
    max_diff = np.max(diff)
    diff_pixels = np.count_nonzero(diff)
    print(f"t={sec:5.1f}s: max_channel_delta={max_diff}, diff_pixels={diff_pixels}")
    assert max_diff == 0, f"Mismatch on t={sec}s: max_delta={max_diff}"

print("\n" + "=" * 75)
print("2. NONE VALUE BEHAVIOR")
print("=" * 75)

kwargs_none = prepare_overlay_frame_data(
    target_dt=start_dt + timedelta(seconds=7.0),
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
    resolve_cache_value=lambda k, src, d, ind=None: None,  # Simulate None for all values
)
img_none = compositor.compose_overlay(1280, 720, layout, "", reuse_canvas=False, **kwargs_none)
assert img_none is not None
print("None value test PASSED: rendered successfully without crash.")

print("\n" + "=" * 75)
print("3. FONT COMPATIBILITY")
print("=" * 75)
fonts_to_test = [
    ("", "default"),
    ("Comic Sans MS", "Comic Sans"),
    ("Digital-7", "Digital-7"),
    ("Iona-u1", "Iona-u1"),
]
for font_name, label_name in fonts_to_test:
    img_font = compositor.compose_overlay(1280, 720, layout, font_name, reuse_canvas=False, **kwargs_seq)
    assert img_font is not None
    print(f"Font '{label_name}' rendered successfully ({img_font.size}).")

print("\nALL ETAP 10M COMPREHENSIVE CHECKS PASSED!")
