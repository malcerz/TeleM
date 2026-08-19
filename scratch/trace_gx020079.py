"""Test with old material GX020079."""
import json
import sys
from pathlib import Path
from datetime import datetime, timezone, timedelta
from PIL import Image

root = Path("c:/_DEV/TeleM")
sys.path.insert(0, str(root))
sys.path.insert(0, str(root / "src"))

from src.telemetry_extract import (
    ensure_records_list, load_json_with_fallback,
    extract_speed_samples, extract_altitude_samples, extract_track_samples,
    extract_iso_samples, extract_exposure_samples, extract_temperature_samples,
    smooth_speed_samples, interpolate_value, get_rotation_from_metadata,
    get_container_rotation, find_metadata_json, extract_gps_track,
    smooth_speed_values, extract_accelerometer_samples, extract_gyroscope_samples,
)
from src.gui.telemetry_manager import TelemetryDataManager
from src.indicators.frame_data import prepare_overlay_frame_data
from src.indicators.compositor import compose_overlay, render_preview

def test_old_material():
    layout = json.load(open(root / "def_layout.json", encoding="utf-8"))
    
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
    
    json_path = root / "Video" / "GX020079.json"
    raw_data = load_json_with_fallback(json_path)
    records = ensure_records_list(raw_data)
    print(f"Loaded GX020079 records: {len(records)}")
    
    telemetry.load_gpmf_records(records)
    telemetry.load_gps_track(records)
    
    fit_path = str(root / "Video" / "Poranna_jazda_na_rowerze.fit")
    telemetry.load_fit(fit_path)
    
    print("\nTelemetry extraction results for GX020079:")
    print(f"  start_dt_utc: {telemetry.start_dt_utc}")
    print(f"  iso_samples: {len(telemetry.iso_samples)}")
    print(f"  exposure_samples: {len(telemetry.exposure_samples)}")
    print(f"  temperature_samples: {len(telemetry.temperature_samples)}")
    print(f"  speed_samples: {len(telemetry.speed_samples)}")
    
    target_dt = telemetry.start_dt_utc or datetime.now(timezone.utc)
    
    frame_data = prepare_overlay_frame_data(
        layout=layout,
        target_dt=target_dt,
        tz_offset_hours=2.0,
        start_dt_utc=telemetry.start_dt_utc,
        speed_samples=telemetry.speed_samples or [],
        track_samples=telemetry.track_samples or [],
        alt_samples=telemetry.alt_samples or [],
        iso_samples=telemetry.iso_samples,
        exposure_samples=telemetry.exposure_samples,
        temperature_samples=telemetry.temperature_samples,
        fit_data=telemetry.fit_data,
        gps_track=telemetry.get_gps_track_for_source("fit"),
        total_frames=60,
        current_index=0,
        resolve_cache_value=lambda k, src, dt, indicator_key=None: telemetry.resolve_value(
            k, dt, source=src, indicator_key=indicator_key
        ),
    )
    
    print("\nFrame data for GX020079:")
    for k in ["date_text", "time_text", "speed_value", "iso_value", "exposure_value", "temp_value"]:
        print(f"  {k}: {frame_data.get(k)}")
        
    bboxes = {}
    font_path = "C:/_DEV/TeleM/resources/fonts/Roboto-Bold.ttf"
    overlay = compose_overlay(
        3840, 2160,
        layout,
        font_path,
        frame_data["date_text"],
        frame_data["time_text"],
        frame_data["speed_value"],
        frame_data["distance_m"],
        frame_data["max_distance_m"],
        frame_data["alt_value"],
        frame_data["min_alt"],
        frame_data["max_alt"],
        frame_data["iso_value"],
        frame_data["exposure_value"],
        frame_data["temp_value"],
        indicator_values=frame_data["indicator_values"],
        max_speed_kmh=frame_data["max_speed_kmh"],
        power_value=frame_data["power_value"],
        atemp_value=frame_data["atemp_value"],
        hr_value=frame_data["hr_value"],
        cad_value=frame_data["cad_value"],
        battery_value=frame_data["battery_value"],
        _bboxes=bboxes,
        extra_indicators=frame_data["extra_indicators"],
        chart_data=frame_data["chart_data"],
        gps_track=frame_data["gps_track"],
        target_dt=frame_data["target_dt"],
        start_dt_utc=frame_data["start_dt_utc"],
    )
    
    print("\nRendered bboxes for GX020079:")
    for k, bb in bboxes.items():
        print(f"  {k}: {bb}")

if __name__ == "__main__":
    test_old_material()
