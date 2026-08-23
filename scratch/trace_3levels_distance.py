import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import json
from src.indicators.compositor import compose_overlay
from src.indicators.dispatcher import render_value_indicator
from src.indicators.bar import _render_ruler
from src.gui.telemetry_manager import TelemetryDataManager
from src.indicators.frame_data import prepare_overlay_frame_data
from src.telemetry_extract import *
from datetime import timedelta, timezone
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

dt = telemetry.start_dt_utc
cfg = v10_layout["indicators"]["dist_visual"]

print("================================================================================")
print("REAL FIT TELEMETRY TRACE FOR DISTANCE (11.9 km ride)")
print("================================================================================")

# In FIT, the ride starts at 09:40:24 and ends at 12:01:15 (23.9 km total).
# The video GX010115 is at 11:18:03 (FIT distance ~11.886 km).
# Let's test across the entire FIT activity at 5 key timestamps:
# 1. Start of FIT activity (09:40:24) -> dist = 0.0 km
# 2. 25% of FIT activity (~10:15:00) -> dist ~ 6.0 km
# 3. Video start (11:18:03) -> dist ~ 11.9 km
# 4. 75% of FIT activity (~11:40:00) -> dist ~ 18.0 km
# 5. End of FIT activity (12:01:15) -> dist ~ 23.9 km

fit_track = telemetry.fit_data["track"]
fit_start_dt = fit_track[0][0]
fit_end_dt = fit_track[-1][0]
fit_total_dist_m = fit_track[-1][1]  # 23926.4 m

test_timestamps = [
    ("FIT Start (0%)", fit_start_dt.replace(tzinfo=timezone.utc) if fit_start_dt.tzinfo is None else fit_start_dt),
    ("FIT 25%", (fit_start_dt + (fit_end_dt - fit_start_dt) * 0.25).replace(tzinfo=timezone.utc) if fit_start_dt.tzinfo is None else fit_start_dt + (fit_end_dt - fit_start_dt) * 0.25),
    ("Video Start (49.7%)", dt),
    ("FIT 75%", (fit_start_dt + (fit_end_dt - fit_start_dt) * 0.75).replace(tzinfo=timezone.utc) if fit_start_dt.tzinfo is None else fit_start_dt + (fit_end_dt - fit_start_dt) * 0.75),
    ("FIT End (100%)", fit_end_dt.replace(tzinfo=timezone.utc) if fit_end_dt.tzinfo is None else fit_end_dt),
]

layout_fit = json.loads(json.dumps(v10_layout))
layout_fit["indicators"]["dist_visual"]["source"] = "fit"

prep_cache = {"max_distance_m": fit_total_dist_m}

for label, target_dt in test_timestamps:
    kw = prepare_overlay_frame_data(
        layout=layout_fit, target_dt=target_dt, tz_offset_hours=2.0, start_dt_utc=telemetry.start_dt_utc,
        speed_samples=telemetry.speed_samples, track_samples=telemetry.track_samples,
        alt_samples=telemetry.alt_samples, iso_samples=telemetry.iso_samples,
        exposure_samples=telemetry.exposure_samples, temperature_samples=telemetry.temperature_samples,
        fit_data=telemetry.fit_data, gps_track=telemetry.get_gps_track_for_source("fit"),
        resolve_cache_value=lambda k, s, d, ind=None: telemetry.resolve_value(k, d, source=s, indicator_key=ind),
        _range_cache=prep_cache,
    )
    
    # 1. Level A: Value calculations
    raw_dist_m = kw["distance_m"]
    val_num_km = raw_dist_m / 1000.0 if raw_dist_m is not None else 0.0
    val_min = 0.0
    val_max = prep_cache["max_distance_m"] / 1000.0  # 23.926 km
    frac = (val_num_km - val_min) / (val_max - val_min)
    
    # 2. Level B: Image returned by _render_ruler / render_value_indicator
    img, rx, ry, _ = render_value_indicator(
        1280, 720, layout_fit, "", "dist_visual", val_num_km, "km", "DISTANCE",
        max_distance_m=prep_cache["max_distance_m"]
    )
    img.save(root / "scratch" / f"bar_dist_{label.replace(' ', '_').replace('(', '').replace(')', '').replace('%', 'pct')}.png")
    
    # Extract marker pixel from img
    arr_b = np.array(img)
    mask_b = (arr_b[:, :, 0] == 255) & (arr_b[:, :, 1] == 212) & (arr_b[:, :, 2] == 42) & (arr_b[:, :, 3] > 200)
    ys_b, xs_b = np.where(mask_b)
    marker_x_level_b = float(np.mean(xs_b)) if len(xs_b) > 0 else None
    
    # 3. Level C: Image after compositor
    bboxes = {}
    overlay = compose_overlay(1280, 720, layout_fit, "", _bboxes=bboxes, **kw)
    bb = bboxes.get("dist_visual")
    ox, oy, ow, oh = bb
    crop = overlay.crop((ox, oy, ox + ow, oy + oh))
    arr_c = np.array(crop)
    mask_c = (arr_c[:, :, 0] == 255) & (arr_c[:, :, 1] == 212) & (arr_c[:, :, 2] == 42) & (arr_c[:, :, 3] > 200)
    ys_c, xs_c = np.where(mask_c)
    marker_x_level_c = float(np.mean(xs_c)) if len(xs_c) > 0 else None
    
    track_w = 358.0
    pad_x = 10.0
    expected_x = pad_x + frac * track_w
    
    print(f"\n{label:<22} | target_dt = {target_dt}")
    print(f"  Raw distance        : {raw_dist_m:.2f} m")
    print(f"  Canonical val_num   : {val_num_km:.3f} km (Range: {val_min:.1f} .. {val_max:.3f} km)")
    print(f"  Calculated frac     : {frac * 100.0:.2f}% (Expected marker_x = {expected_x:.1f} px)")
    print(f"  Raster BEFORE comp  : marker_x = {marker_x_level_b:.1f} px")
    print(f"  Raster AFTER comp   : marker_x = {marker_x_level_c:.1f} px (Canvas bbox: {bb})")
