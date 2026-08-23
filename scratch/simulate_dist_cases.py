import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import json
from src.indicators.compositor import compose_overlay
from src.indicators.dispatcher import render_value_indicator
from src.gui.telemetry_manager import TelemetryDataManager
from src.indicators.frame_data import prepare_overlay_frame_data
from src.telemetry_extract import *
from datetime import timedelta
import numpy as np

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

print("Let's test all possible distance configurations at target_dt = start_dt_utc (where FIT distance = 11.9 km):")

dt = telemetry.start_dt_utc

# Test Case 1: dist_visual with source="fit" in layout
layout1 = json.loads(json.dumps(v10_layout))
layout1["indicators"]["dist_visual"]["source"] = "fit"

kw1 = prepare_overlay_frame_data(
    target_dt=dt, start_dt_utc=dt, tz_offset_hours=2.0, layout=layout1,
    speed_samples=telemetry.speed_samples, track_samples=telemetry.track_samples,
    alt_samples=telemetry.alt_samples, iso_samples=telemetry.iso_samples,
    exposure_samples=telemetry.exposure_samples, temperature_samples=telemetry.temperature_samples,
    fit_data=telemetry.fit_data, gps_track=telemetry.get_gps_track_for_source("fit"),
    resolve_cache_value=lambda k, s, d, ind=None: telemetry.resolve_value(k, d, source=s),
)

print("\n--- CASE 1: dist_visual (source='fit') ---")
print("kw1 distance_m:", kw1.get("distance_m"))
print("kw1 max_distance_m:", kw1.get("max_distance_m"))
print("kw1 indicator_values:", kw1.get("indicator_values", {}).get("dist_visual"))

# Test Case 2: fit_distance_text with form="bar", bar_style="ruler"
layout2 = json.loads(json.dumps(v10_layout))
layout2["indicators"]["fit_distance_text"] = {
    "enabled": True, "label": "DISTANCE", "x": 50.0, "y": 74.0, "rotation": 0,
    "form": "bar", "bar_style": "ruler", "font_size": 1.2, "size": 28.0, "thickness": 1,
    "min_val": 0.0, "max_val": 25.0, "ticks": 5, "show_value": True, "source": "fit", "unit": "km"
}

kw2 = prepare_overlay_frame_data(
    target_dt=dt, start_dt_utc=dt, tz_offset_hours=2.0, layout=layout2,
    speed_samples=telemetry.speed_samples, track_samples=telemetry.track_samples,
    alt_samples=telemetry.alt_samples, iso_samples=telemetry.iso_samples,
    exposure_samples=telemetry.exposure_samples, temperature_samples=telemetry.temperature_samples,
    fit_data=telemetry.fit_data, gps_track=telemetry.get_gps_track_for_source("fit"),
    extra_field_keys=["distance"],
    resolve_cache_value=lambda k, s, d, ind=None: telemetry.resolve_value(k, d, source=s),
)

print("\n--- CASE 2: fit_distance_text (form='bar', unit='km') ---")
print("resolved 'distance':", telemetry.resolve_value("distance", dt, source="fit"))
print("kw2 extra_indicators:", kw2.get("extra_indicators"))

# Test Case 3: dist_text with form="bar", bar_style="ruler", source="fit"
layout3 = json.loads(json.dumps(v10_layout))
layout3["indicators"]["dist_text"] = {
    "enabled": True, "label": "DISTANCE", "x": 50.0, "y": 74.0, "rotation": 0,
    "form": "bar", "bar_style": "ruler", "font_size": 1.2, "size": 28.0, "thickness": 1,
    "min_val": 0.0, "max_val": 25.0, "ticks": 5, "show_value": True, "source": "fit", "unit": "km"
}

kw3 = prepare_overlay_frame_data(
    target_dt=dt, start_dt_utc=dt, tz_offset_hours=2.0, layout=layout3,
    speed_samples=telemetry.speed_samples, track_samples=telemetry.track_samples,
    alt_samples=telemetry.alt_samples, iso_samples=telemetry.iso_samples,
    exposure_samples=telemetry.exposure_samples, temperature_samples=telemetry.temperature_samples,
    fit_data=telemetry.fit_data, gps_track=telemetry.get_gps_track_for_source("fit"),
    resolve_cache_value=lambda k, s, d, ind=None: telemetry.resolve_value(k, d, source=s),
)

print("\n--- CASE 3: dist_text (form='bar', source='fit') ---")
print("kw3 distance_m:", kw3.get("distance_m"))
print("kw3 indicator_values:", kw3.get("indicator_values", {}).get("dist_text"))
