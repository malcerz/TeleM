"""Reproduce the real GUI AMD export call for ETAP 5E production validation.

Same call as the validated ETAP 4/5A/5B/5C/5D production GUI exports
(``stream_overlay_to_ffmpeg`` → ``AMD_NATIVE_D3D11``). The final-compositing
implementation is selected by ``AMD_PIL_COMPOSITE_MODE`` (REFERENCE|OPTIMIZED);
after the 5E pixel test passes, OPTIMIZED is the production default.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.ffmpeg.streaming import stream_overlay_to_ffmpeg
from src.gui.layout_manager import resolve_font_path
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
    parser.add_argument("--output", default="Raporty/AMD_ETAP5E/after_production_1131.mp4")
    args = parser.parse_args()
    root = ROOT
    video = root / "Video" / "GX020079.mp4"
    output = Path(args.output)
    if not output.is_absolute():
        output = root / output
    output.parent.mkdir(parents=True, exist_ok=True)

    records = ensure_records_list(
        load_json_with_fallback(root / "Video" / "GX020079.json")
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
    )
    telemetry.load_gpmf_records(records)
    telemetry.load_fit(root / "Video" / "Morning_Ride.fit")
    telemetry.start_dt_utc = datetime(2026, 8, 5, 4, 28, 11)

    with (root / "def_layout.json").open(encoding="utf-8") as handle:
        layout = json.load(handle)

    speed = smooth_speed_samples(telemetry.speed_samples, "moving_average", 5)
    altitude = smooth_speed_samples(telemetry.alt_samples, "moving_average", 5)
    track = telemetry.track_samples
    result = stream_overlay_to_ffmpeg(
        ffmpeg_exe=r"C:\tools\ffmpeg.exe",
        input_files=[str(video)],
        output_file=str(output),
        duration_s=37.7377,
        start_dt_utc=telemetry.start_dt_utc,
        tz_offset_hours=2,
        speed_samples=speed,
        track_samples=track,
        alt_samples=altitude,
        font_path=resolve_font_path("Arial"),
        layout=layout,
        field_samples={
            "speed_samples": speed,
            "track_samples": track,
            "alt_samples": altitude,
        },
        max_distance_m=track[-1][1] if track else 0,
        target_fps=30000 / 1001,
        update_rate_step=1,
        workers=1,
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
        gps_track=telemetry.get_gps_track_for_source(
            layout.get("indicators", {}).get("track_map", {}).get("source", "fit")
        ),
        encoder="amd",
        gpu=0,
        video_bitrate="40M",
        render_w=3840,
        render_h=2160,
        resolution_name="source",
        rotation_degrees=180,
        container_rotation=180,
        overlay_w=1920,
        overlay_h=1080,
    )
    return 0 if result == 1131 else 1


if __name__ == "__main__":
    raise SystemExit(main())
