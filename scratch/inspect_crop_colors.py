import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import json
from src.indicators.compositor import compose_overlay
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

dt = telemetry.start_dt_utc
kw = prepare_overlay_frame_data(
    layout=v10_layout, target_dt=dt, tz_offset_hours=2.0, start_dt_utc=dt,
    speed_samples=telemetry.speed_samples, track_samples=telemetry.track_samples,
    alt_samples=telemetry.alt_samples, iso_samples=telemetry.iso_samples,
    exposure_samples=telemetry.exposure_samples, temperature_samples=telemetry.temperature_samples,
    fit_data=telemetry.fit_data, gps_track=telemetry.get_gps_track_for_source("fit"),
    resolve_cache_value=lambda k, s, d, ind=None: telemetry.resolve_value(k, d, source=s, indicator_key=ind),
)
bboxes = {}
overlay = compose_overlay(1280, 720, v10_layout, "", _bboxes=bboxes, **kw)
bb = bboxes.get("dist_visual")
print("dist_visual bbox:", bb)
ox, oy, ow, oh = bb
crop = overlay.crop((ox, oy, ox + ow, oy + oh))
crop.save(root / "scratch" / "dist_visual_crop.png")

# Inspect non-transparent pixels in crop
arr = np.array(crop)
non_zero = arr[arr[:, :, 3] > 0]
print("Unique colors in crop (top 20):")
unique_colors, counts = np.unique(non_zero, axis=0, return_counts=True)
sorted_idx = np.argsort(-counts)
for idx in sorted_idx[:20]:
    print(f"Color: {unique_colors[idx]} | Count: {counts[idx]}")
