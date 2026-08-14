"""Reproducible real-input runner for AMD ETAP 2 validation."""

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, os.path.abspath("."))

from src.ffmpeg.amd_native_exporter import export_amd_native_d3d11
from src.gui.telemetry_manager import TelemetryDataManager
from src.telemetry_extract import (
    ensure_records_list,
    extract_altitude_samples,
    extract_exposure_samples,
    extract_iso_samples,
    extract_speed_samples,
    extract_temperature_samples,
    extract_track_samples,
    interpolate_value,
    load_json_with_fallback,
    smooth_speed_samples,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    parser.add_argument("--input", default="Video/GX020079.mp4")
    parser.add_argument("--duration", type=float, default=37.74)
    parser.add_argument("--static-hud", action="store_true")
    parser.add_argument("--hud-off", action="store_true")
    args = parser.parse_args()

    video_path = os.path.abspath(args.input)
    records = ensure_records_list(load_json_with_fallback(Path("Video/GX020079.json")))
    telemetry = TelemetryDataManager(
        extract_speed_fn=extract_speed_samples,
        extract_altitude_fn=extract_altitude_samples,
        extract_track_fn=extract_track_samples,
        extract_iso_fn=extract_iso_samples,
        extract_exposure_fn=extract_exposure_samples,
        extract_temperature_fn=extract_temperature_samples,
        smooth_fn=smooth_speed_samples,
        interpolate_fn=interpolate_value,
    )
    telemetry.load_gpmf_records(records)
    telemetry.load_fit(os.path.abspath("Video/Morning_Ride.fit"))
    telemetry.start_dt_utc = datetime(2026, 8, 5, 4, 28, 11)

    if args.hud_off:
        layout = {
            "version": 6,
            "global": {"text_outline": 3},
            "indicators": {},
            "custom_texts": [],
        }
    elif args.static_hud:
        layout = {
            "version": 6,
            "global": {"text_outline": 3},
            "indicators": {},
            "custom_texts": [{
                "enabled": True,
                "text": "AMD ETAP 2 GPU HUD",
                "x": 50.0,
                "y": 50.0,
                "font_size": 4.0,
                "color": "#FF8000",
                "rotation": 0,
            }],
        }
    else:
        with open("def_layout.json", "r", encoding="utf-8") as layout_file:
            layout = json.load(layout_file)

    font_path = os.path.abspath("include/fonts/Roboto-Bold.ttf")
    if not os.path.exists(font_path):
        font_path = "arial.ttf"

    result = export_amd_native_d3d11(
        ffmpeg_exe=r"C:\tools\ffmpeg.exe",
        input_files=[video_path],
        output_file=os.path.abspath(args.output),
        duration_s=args.duration,
        video_width=3840,
        video_height=2160,
        start_dt_utc=telemetry.start_dt_utc,
        tz_offset_hours=0.0,
        speed_samples=telemetry.speed_samples,
        track_samples=telemetry.track_samples,
        alt_samples=telemetry.alt_samples,
        font_path=font_path,
        layout=layout,
        field_samples={
            "speed_samples": telemetry.speed_samples,
            "track_samples": telemetry.track_samples,
            "alt_samples": telemetry.alt_samples,
        },
        target_fps=29.97,
        iso_samples=telemetry.iso_samples,
        exposure_samples=telemetry.exposure_samples,
        temperature_samples=telemetry.temperature_samples,
        fit_data=telemetry.fit_data,
        gps_track=telemetry.fit_gps_track,
    )
    return 0 if result else 1


if __name__ == "__main__":
    raise SystemExit(main())
