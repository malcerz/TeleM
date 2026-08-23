import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import json
from PIL import Image
import numpy as np
from src.indicators.bar import _render_ruler
from src.indicators.dispatcher import render_value_indicator
from src.indicators.compositor import compose_overlay
from src.gui.telemetry_manager import TelemetryDataManager
from src.indicators.frame_data import prepare_overlay_frame_data
from src.telemetry_extract import (
    extract_speed_samples, extract_altitude_samples, extract_track_samples,
    extract_iso_samples, extract_exposure_samples, extract_temperature_samples,
    ensure_records_list, extract_gps_track,
    smooth_speed_samples, interpolate_value, get_rotation_from_metadata,
    get_container_rotation, find_metadata_json, load_json_with_fallback,
    smooth_speed_values, extract_accelerometer_samples, extract_gyroscope_samples,
)
from datetime import timedelta

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

print("Track samples count (GPMF):", len(telemetry.track_samples))
print("Track samples count (FIT):", len(telemetry.fit_data.get("track", [])))
print("Distance samples count (FIT):", len(telemetry.fit_data.get("distance", [])))

for frame_idx in [0, 30, 60, 90, 119]:
    dt = start_dt + timedelta(seconds=frame_idx / fps)
    kw = prepare_overlay_frame_data(
        target_dt=dt, start_dt_utc=start_dt, tz_offset_hours=2.0, layout=v10_layout,
        speed_samples=telemetry.speed_samples, track_samples=telemetry.track_samples,
        alt_samples=telemetry.alt_samples, iso_samples=telemetry.iso_samples,
        exposure_samples=telemetry.exposure_samples, temperature_samples=telemetry.temperature_samples,
        fit_data=telemetry.fit_data, gps_track=telemetry.get_gps_track_for_source("fit"),
        resolve_cache_value=lambda k, src, d, ind=None: telemetry.resolve_value(k, d, source=src),
    )
    print(f"\n--- Frame {frame_idx} (dt={dt}) ---")
    print("distance_m from kw:", kw.get("distance_m"))
    print("indicator_values['dist_visual']:", kw.get("indicator_values", {}).get("dist_visual"))
    print("max_distance_m:", kw.get("max_distance_m"))

    # Now let's see what compose_overlay does
    bboxes = {}
    overlay = compose_overlay(canvas_w, canvas_h, v10_layout, "", _bboxes=bboxes, **kw)
