"""Inspect GX020079.mp4 and Morning_Ride.fit metadata."""
import sys
from pathlib import Path

root = Path("c:/_DEV/TeleM")
sys.path.insert(0, str(root))
sys.path.insert(0, str(root / "src"))

from src.gui.telemetry_manager import TelemetryDataManager
from src.telemetry_extract import (
    ensure_records_list, load_json_with_fallback,
    extract_speed_samples, extract_altitude_samples, extract_track_samples,
    extract_iso_samples, extract_exposure_samples, extract_temperature_samples,
    smooth_speed_samples, interpolate_value, get_rotation_from_metadata,
    get_container_rotation, find_metadata_json, extract_gps_track,
    smooth_speed_values, extract_accelerometer_samples, extract_gyroscope_samples,
)

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

records = ensure_records_list(load_json_with_fallback(root / "Video" / "GX020079.json"))
telemetry.load_gpmf_records(records)
telemetry.load_fit(str(root / "Video" / "Morning_Ride.fit"))

print(f"GPMF start_dt_utc: {telemetry.start_dt_utc}")
gpmf_dur = (telemetry.speed_samples[-1][0] - telemetry.speed_samples[0][0]).total_seconds() if telemetry.speed_samples else 0
print(f"GPMF speed samples: {len(telemetry.speed_samples)} duration: {gpmf_dur:.2f} s")

for k, v in telemetry.fit_data.items():
    if v:
        dur = (v[-1][0] - v[0][0]).total_seconds()
        print(f"FIT field {k:15s}: {len(v):5d} samples, start={v[0][0]}, end={v[-1][0]} duration={dur:.1f} s ({dur/60:.1f} min)")
