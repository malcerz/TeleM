import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import json
import numpy as np
from datetime import timedelta
from src.gui.telemetry_manager import TelemetryDataManager
from src.indicators.frame_data import prepare_overlay_frame_data
from src.indicators.compositor import compose_overlay
from src.indicators.dispatcher import render_value_indicator
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

duration = getattr(telemetry, "video_duration_s", None) or 120.0
print("Video duration:", duration)
print("GPMF track start:", telemetry.track_samples[0] if telemetry.track_samples else None)
print("GPMF track end:", telemetry.track_samples[-1] if telemetry.track_samples else None)
fit_track = telemetry.fit_data.get("track", [])
print("FIT track start:", fit_track[0] if fit_track else None)
print("FIT track end:", fit_track[-1] if fit_track else None)

def get_marker_x_from_image(img, marker_color=(255, 212, 42)):
    # Find pixels matching marker_color in img
    arr = np.array(img)
    # marker_color is RGB, arr is RGBA
    mask = (arr[:, :, 0] == marker_color[0]) & (arr[:, :, 1] == marker_color[1]) & (arr[:, :, 2] == marker_color[2]) & (arr[:, :, 3] > 200)
    ys, xs = np.where(mask)
    if len(xs) > 0:
        return float(np.mean(xs))
    return None

# Check for both GPMF and FIT source
for src in ["gpmf", "fit"]:
    cfg = v10_layout["indicators"]["dist_visual"].copy()
    cfg["source"] = src
    l = json.loads(json.dumps(v10_layout))
    l["indicators"]["dist_visual"] = cfg

    print(f"\n==================== SOURCE: {src} ====================")
    # Check across various timestamps in video
    for ts in [0.0, 30.0, 60.0, 90.0, duration]:
        dt = telemetry.start_dt_utc + timedelta(seconds=ts)
        kw = prepare_overlay_frame_data(
            target_dt=dt, start_dt_utc=telemetry.start_dt_utc, tz_offset_hours=2.0, layout=l,
            speed_samples=telemetry.speed_samples, track_samples=telemetry.track_samples,
            alt_samples=telemetry.alt_samples, iso_samples=telemetry.iso_samples,
            exposure_samples=telemetry.exposure_samples, temperature_samples=telemetry.temperature_samples,
            fit_data=telemetry.fit_data, gps_track=telemetry.get_gps_track_for_source("fit"),
            resolve_cache_value=lambda k, s, d, ind=None: telemetry.resolve_value(k, d, source=s),
        )
        dist_m = kw.get("distance_m")
        max_dist_m = kw.get("max_distance_m")
        val = dist_m / 1000.0 if dist_m is not None else None
        
        # Test compositor / render_value_indicator directly
        img, rx, ry, _ = render_value_indicator(
            1280, 720, l, "", "dist_visual", val if val is not None else 0.0, "km", "DISTANCE",
            cfg_override=cfg, max_distance_m=max_dist_m
        )
        marker_x = get_marker_x_from_image(img)
        print(f"t={ts:6.1f}s | raw_m={dist_m:8.1f}m | display_val={val:.4f} km | max_val_m={max_dist_m:.1f}m | marker_x={marker_x}")

