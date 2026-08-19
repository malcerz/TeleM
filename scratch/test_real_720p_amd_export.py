"""Run real 720p AMD native export and inspect output frame 30."""
import json
import sys
import os
from pathlib import Path
from datetime import datetime, timezone, timedelta
from PIL import Image

root = Path("c:/_DEV/TeleM")
sys.path.insert(0, str(root))
sys.path.insert(0, str(root / "src"))

from src.gui.layout_manager import normalize_layout, resolve_font_path
from src.gui.telemetry_manager import TelemetryDataManager
from src.gui.indicator_schemas import BUILTIN_FIELDS
from src.telemetry_extract import (
    ensure_records_list, load_json_with_fallback,
    extract_speed_samples, extract_altitude_samples, extract_track_samples,
    extract_iso_samples, extract_exposure_samples, extract_temperature_samples,
    smooth_speed_samples, interpolate_value, get_rotation_from_metadata,
    get_container_rotation, find_metadata_json, extract_gps_track,
    smooth_speed_values, extract_accelerometer_samples, extract_gyroscope_samples,
)
from src.ffmpeg.amd_native_exporter import export_amd_native_d3d11

def run_720p_export():
    print("=== Running Real 720p AMD Export (60 frames) ===")
    
    def_layout_path = root / "def_layout.json"
    with open(def_layout_path, "r", encoding="utf-8") as f:
        layout = json.load(f)
        
    font_path = resolve_font_path("Arial")
    video_path = root / "Video" / "GX030120.MP4"
    json_path = root / "Video" / "GX030120.json"
    fit_path = root / "Video" / "Popoludniowa_jazda_na_rowerze_solar_battery.fit"
    
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
    
    raw_data = load_json_with_fallback(json_path)
    records = ensure_records_list(raw_data)
    telemetry.load_gpmf_records(records)
    telemetry.load_gps_track(records)
    telemetry.load_fit(str(fit_path))
    
    fit_keys = telemetry.register_fit_fields(layout, BUILTIN_FIELDS)
    
    out_mp4 = root / "scratch" / "etap8m3_720p_export.mp4"
    from src.video_helpers import find_executable
    ffmpeg_exe = find_executable("ffmpeg") or "C:\\tools\\ffmpeg.exe"
    
    field_samples = {
        "speed_samples": telemetry.speed_samples or [],
        "track_samples": telemetry.track_samples or [],
        "alt_samples": telemetry.alt_samples or [],
        "iso_samples": telemetry.iso_samples or [],
        "exposure_samples": telemetry.exposure_samples or [],
        "temperature_samples": telemetry.temperature_samples or [],
    }
    
    ok = export_amd_native_d3d11(
        ffmpeg_exe=ffmpeg_exe,
        input_files=[video_path],
        output_file=str(out_mp4),
        duration_s=60.0 / 29.97,
        video_width=1280,
        video_height=720,
        start_dt_utc=telemetry.start_dt_utc,
        tz_offset_hours=2,
        speed_samples=telemetry.speed_samples or [],
        track_samples=telemetry.track_samples or [],
        alt_samples=telemetry.alt_samples or [],
        font_path=font_path,
        layout=layout,
        field_samples=field_samples,
        target_fps=29.97,
        video_bitrate="20M",
        max_distance_m=None,
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
        progress_cb=None,
        on_render_progress=None,
        cancel_event=None,
        active_process_holder=None,
    )
    print(f"Export returned: {ok}")

if __name__ == "__main__":
    run_720p_export()
