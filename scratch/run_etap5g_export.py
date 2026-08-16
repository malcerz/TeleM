"""ETAP 5G — real GUI AMD export runner with GPU map path control.

Usage examples:
  python scratch/run_etap5g_export.py --frames 30 --map-path GPU --filter LANCZOS \
      --output Raporty/AMD_ETAP5G/gpu30.mp4
  python scratch/run_etap5g_export.py --frames 1131 --map-path CPU_REFERENCE \
      --output Raporty/AMD_ETAP5G/ref1131.mp4
"""
from __future__ import annotations

import argparse
import json
import os
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
    parser.add_argument("--frames", type=int, default=1131)
    parser.add_argument("--map-path", choices=["CPU_REFERENCE", "GPU"], default="GPU")
    parser.add_argument("--filter", choices=["BILINEAR", "BICUBIC", "LANCZOS"], default="LANCZOS")
    parser.add_argument("--chart-path", choices=["CPU_REFERENCE", "GPU", "GPU_SPLIT"], default=None,
                        help="ETAP 5J/5K: charts in Pillow HUD (CPU_REFERENCE), GPU blend "
                             "(GPU), or GPU static+dynamic split (GPU_SPLIT). "
                             "Overrides AMD_CHART_PATH env var.")
    parser.add_argument("--gauge-path", choices=["CPU_REFERENCE", "GPU"], default=None,
                        help="ETAP 5L: speed gauge in Pillow HUD (CPU_REFERENCE) or GPU "
                             "blend (GPU). Overrides AMD_GAUGE_PATH env var.")
    parser.add_argument("--output", default="Raporty/AMD_ETAP5G/export.mp4")
    parser.add_argument("--input", default="Video/GX020079.mp4")
    parser.add_argument("--profile", action="store_true", default=False)
    args = parser.parse_args()

    if args.chart_path:
        os.environ["AMD_CHART_PATH"] = args.chart_path
    if args.gauge_path:
        os.environ["AMD_GAUGE_PATH"] = args.gauge_path

    duration_s = args.frames * (1001.0 / 30000.0)
    root = ROOT
    video = root / args.input
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
        duration_s=duration_s,
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
    return 0 if result == args.frames else 1


if __name__ == "__main__":
    raise SystemExit(main())
