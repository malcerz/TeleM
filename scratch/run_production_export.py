import os
import sys
from pathlib import Path
from datetime import datetime

# Add root directory to sys.path
sys.path.insert(0, os.path.abspath("."))

from src.telemetry_extract import (
    load_json_with_fallback,
    ensure_records_list,
    extract_speed_samples,
    extract_track_samples,
    extract_altitude_samples,
    extract_iso_samples,
    extract_exposure_samples,
    extract_temperature_samples,
    smooth_speed_samples,
    interpolate_value,
)
from src.gui.telemetry_manager import TelemetryDataManager
from src.ffmpeg.amd_native_exporter import export_amd_native_d3d11

def main():
    video_path = os.path.abspath("Video/GX020079.mp4")
    meta_path = os.path.abspath("Video/GX020079.json")
    fit_path = os.path.abspath("Video/Morning_Ride.fit")
    output_path = os.path.abspath("05_final_muxed.mp4")
    ffmpeg_exe = r"c:\tools\ffmpeg.exe"

    print(f"Loading Telemetry: GPMF={meta_path}, FIT={fit_path}")
    records = ensure_records_list(load_json_with_fallback(Path(meta_path)))

    tm = TelemetryDataManager(
        extract_speed_fn=extract_speed_samples,
        extract_altitude_fn=extract_altitude_samples,
        extract_track_fn=extract_track_samples,
        extract_iso_fn=extract_iso_samples,
        extract_exposure_fn=extract_exposure_samples,
        extract_temperature_fn=extract_temperature_samples,
        smooth_fn=smooth_speed_samples,
        interpolate_fn=interpolate_value,
    )
    tm.load_gpmf_records(records)
    tm.load_fit(fit_path)
    tm.start_dt_utc = datetime(2026, 8, 5, 4, 28, 11)

    import json
    layout_path = os.path.abspath("def_layout.json")
    with open(layout_path, "r", encoding="utf-8") as f:
        layout = json.load(f)

    font_path = os.path.abspath("include/fonts/Roboto-Bold.ttf")
    if not os.path.exists(font_path):
        font_path = "arial.ttf"

    field_samples = {
        "speed_samples": tm.speed_samples,
        "track_samples": tm.track_samples,
        "alt_samples": tm.alt_samples,
    }

    print("Running export_amd_native_d3d11...")
    res = export_amd_native_d3d11(
        ffmpeg_exe=ffmpeg_exe,
        input_files=[video_path],
        output_file=output_path,
        duration_s=37.74,
        video_width=3840,
        video_height=2160,
        start_dt_utc=tm.start_dt_utc,
        tz_offset_hours=0.0,
        speed_samples=tm.speed_samples,
        track_samples=tm.track_samples,
        alt_samples=tm.alt_samples,
        font_path=font_path,
        layout=layout,
        field_samples=field_samples,
        target_fps=29.97,
        iso_samples=tm.iso_samples,
        exposure_samples=tm.exposure_samples,
        temperature_samples=tm.temperature_samples,
        fit_data=tm.fit_data,
        gps_track=tm.fit_gps_track,
    )
    print(f"Export result: {res}")

if __name__ == "__main__":
    main()
