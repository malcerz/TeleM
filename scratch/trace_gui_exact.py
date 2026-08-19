"""Exact simulation of Qt Controller loading GX020079 and rendering Preview."""
import json
import sys
from pathlib import Path
from datetime import datetime, timezone, timedelta
from PIL import Image

root = Path("c:/_DEV/TeleM")
sys.path.insert(0, str(root))
sys.path.insert(0, str(root / "src"))

from src.gui.layout_manager import normalize_layout, default_layout, resolve_font_path
from src.gui.telemetry_manager import TelemetryDataManager
from src.telemetry_extract import (
    ensure_records_list, load_json_with_fallback,
    extract_speed_samples, extract_altitude_samples, extract_track_samples,
    extract_iso_samples, extract_exposure_samples, extract_temperature_samples,
    smooth_speed_samples, interpolate_value, get_rotation_from_metadata,
    get_container_rotation, find_metadata_json, extract_gps_track,
    smooth_speed_values, extract_accelerometer_samples, extract_gyroscope_samples,
)
from src.overlay_renderer import (
    prepare_overlay_frame_data, build_chart_data, render_preview, compose_overlay
)

def run_exact_preview():
    print("=== 1. Controller Init ===")
    font_path = resolve_font_path("Arial")
    print(f"Resolved font_path: {font_path}")
    
    def_layout_path = root / "def_layout.json"
    layout = normalize_layout(def_layout_path, 1280, 720)
    
    print("\n=== 2. TelemetryManager Init ===")
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
    
    print("\n=== 3. Load Video Metadata (ProjectMixin._load_telemetry_for_video) ===")
    video_path = root / "Video" / "GX020079.mp4"
    json_path = root / "Video" / "GX020079.json"
    raw_data = load_json_with_fallback(json_path)
    records = ensure_records_list(raw_data)
    
    telemetry.load_gpmf_records(records)
    telemetry.load_gps_track(records)
    
    fit_path = root / "Video" / "Poranna_jazda_na_rowerze.fit"
    telemetry.load_fit(str(fit_path))
    
    print(f"start_dt_utc: {telemetry.start_dt_utc}")
    print(f"iso_samples: {len(telemetry.iso_samples)}")
    print(f"exposure_samples: {len(telemetry.exposure_samples)}")
    print(f"temperature_samples: {len(telemetry.temperature_samples)}")
    
    print("\n=== 4. Build Chart Data & Prepare Cache ===")
    chart_data = build_chart_data(
        layout,
        telemetry.get_samples_for_source,
        lambda field, src, key=None: telemetry.resolve_samples(field, src, indicator_key=key),
        start_dt_utc=telemetry.start_dt_utc,
        end_dt_utc=(telemetry.start_dt_utc + timedelta(seconds=37.7)) if telemetry.start_dt_utc else None,
    )
    
    print("\n=== 5. PreviewMixin._render_preview(0) ===")
    target_dt = telemetry.start_dt_utc
    if target_dt and target_dt.tzinfo is None:
        target_dt = target_dt.replace(tzinfo=timezone.utc)
        
    prepare_cache = {
        "min_alt": None, "max_alt": None, "max_speed_kmh": None,
        "fit_fields": {}
    }
    
    overlay_data = prepare_overlay_frame_data(
        layout=layout,
        target_dt=target_dt,
        tz_offset_hours=2,
        start_dt_utc=telemetry.start_dt_utc,
        speed_samples=telemetry.speed_samples or [],
        track_samples=telemetry.track_samples or [],
        alt_samples=telemetry.alt_samples or [],
        iso_samples=telemetry.iso_samples,
        exposure_samples=telemetry.exposure_samples,
        temperature_samples=telemetry.temperature_samples,
        gpx_speed_samples=telemetry.gpx_speed_samples,
        gpx_track_samples=telemetry.gpx_track_samples,
        gpx_alt_samples=telemetry.gpx_alt_samples,
        gpx_power_samples=telemetry.gpx_power_samples,
        gpx_atemp_samples=telemetry.gpx_atemp_samples,
        gpx_hr_samples=telemetry.gpx_hr_samples,
        gpx_cad_samples=telemetry.gpx_cad_samples,
        fit_data=telemetry.fit_data,
        gps_track=telemetry.get_gps_track_for_source("fit"),
        total_frames=37,
        current_index=0,
        chart_data=chart_data,
        extra_field_keys=None,
        resolve_cache_value=lambda k, src, dt, indicator_key=None: telemetry.resolve_value(
            k, dt, source=src, indicator_key=indicator_key
        ),
        _range_cache=prepare_cache,
    )
    
    print("overlay_data results:")
    for k in ["date_text", "time_text", "speed_value", "iso_value", "exposure_value", "temp_value"]:
        print(f"  {k}: {overlay_data.get(k)}")
        
    print("\n=== 6. Render Preview (src_img 1280x720) ===")
    src_img = Image.new("RGBA", (1280, 720), (30, 30, 30, 255))
    indicator_bboxes = {}
    
    preview = render_preview(
        src_img, layout, font_path,
        overlay_data["date_text"], overlay_data["time_text"],
        overlay_data["speed_value"],
        overlay_data["distance_m"],
        overlay_data["max_distance_m"],
        overlay_data["alt_value"],
        overlay_data["min_alt"],
        overlay_data["max_alt"],
        overlay_data["iso_value"],
        overlay_data["exposure_value"],
        overlay_data["temp_value"],
        indicator_values=overlay_data["indicator_values"],
        max_speed_kmh=overlay_data["max_speed_kmh"],
        power_value=overlay_data["power_value"],
        atemp_value=overlay_data["atemp_value"],
        hr_value=overlay_data["hr_value"],
        cad_value=overlay_data["cad_value"],
        battery_value=overlay_data["battery_value"],
        _bboxes=indicator_bboxes,
        extra_indicators=overlay_data["extra_indicators"],
        chart_data=overlay_data["chart_data"],
        current_position=0.0,
        gps_track=overlay_data["gps_track"],
        target_dt=overlay_data["target_dt"],
        start_dt_utc=overlay_data["start_dt_utc"],
        elapsed_seconds=overlay_data["elapsed_seconds"],
        avg_speed_kmh=overlay_data["avg_speed_kmh"],
        inplace=False,
    )
    
    print("\nRendered bboxes in Preview:")
    for k, bb in indicator_bboxes.items():
        print(f"  {k}: {bb}")
        
    preview.save(root / "scratch" / "preview_1280x720.png")
    print("Saved preview to scratch/preview_1280x720.png")

if __name__ == "__main__":
    run_exact_preview()
