"""
Quick test of GPU timestamp profile output.
"""
import os
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
from src.gui.layout_manager import normalize_layout
from src.ffmpeg.amd_native_exporter import export_amd_native_d3d11

v_1131 = root / "Video" / "GX020079.mp4"
fit_1131 = root / "Video" / "Morning_Ride.fit"

def test_timeline():
    os.environ["AMD_TELEMETRY_MODE"] = "PRECOMPUTED"
    os.environ["AMD_GPU_TIMESTAMP_PROFILE"] = "1"
    os.environ["AMD_CPU_GPU_PIPELINE"] = "SYNC"
    os.environ["AMD_MAP_GPU_PATH"] = "DIRECT_AUTO"
    
    tm = TelemetryDataManager(
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
    records = ensure_records_list(load_json_with_fallback(v_1131.with_suffix(".json")))
    tm.load_gpmf_records(records)
    tm.load_fit(str(fit_1131))
    
    layout = normalize_layout(root / "def_layout.json", 3840, 2160)
    out_mp4 = root / "scratch" / "test_ts_out.mp4"
    if out_mp4.exists():
        out_mp4.unlink()
        
    ok = export_amd_native_d3d11(
        ffmpeg_exe="ffmpeg",
        input_files=[str(v_1131)],
        output_file=str(out_mp4),
        duration_s=60 / 29.97, # 60 frames
        video_width=3840,
        video_height=2160,
        start_dt_utc=tm.start_dt_utc,
        tz_offset_hours=2.0,
        speed_samples=tm.speed_samples or [],
        track_samples=tm.track_samples or [],
        alt_samples=tm.alt_samples or [],
        font_path="assets/Roboto-Bold.ttf",
        layout=layout,
        field_samples=tm.fit_data or {},
        iso_samples=tm.iso_samples,
        exposure_samples=tm.exposure_samples,
        temperature_samples=tm.temperature_samples,
        fit_data=tm.fit_data,
        gps_track=tm.get_gps_track_for_source("fit"),
    )
    csv_file = out_mp4.with_suffix(".mp4.gpu_timeline.csv")
    print(f"Export ok: {ok}, CSV exists: {csv_file.exists()}")
    if csv_file.exists():
        with open(csv_file) as f:
            lines = [f.readline() for _ in range(10)]
            print("CSV Header + first few lines:")
            print("".join(lines))

if __name__ == "__main__":
    test_timeline()
