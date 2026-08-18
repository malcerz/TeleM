"""ETAP 8B diagnostic runner for the real GX030120 material."""
from __future__ import annotations

import argparse
import copy
import json
import os
import sys
from datetime import datetime
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("--tag", required=True)
parser.add_argument("--charts", type=int, choices=(0, 1, 2), default=2)
args = parser.parse_args()
root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root))

os.environ.update({
    "AMD_MAP_PATH": "GPU",
    "AMD_MAP_FILTER": "LANCZOS",
    "AMD_CHART_PATH": "GPU_SPLIT",
    "AMD_GAUGE_PATH": "GPU",
    "AMD_TELEMETRY_MODE": "PRECOMPUTED",
    "AMD_OVERLAY_PROFILE": "1",
    "AMD_FRAME_ACCOUNTING": "1",
    "AMD_AMF_DIAG": "1",
    "AMD_GPU_TIMESTAMP_PROFILE": "1",
})

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

records = ensure_records_list(load_json_with_fallback(root / "Video" / "GX030120.json"))
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
tm.load_fit(root / "Video" / "Poranna_jazda_na_rowerze.fit")
tm.start_dt_utc = datetime(2026, 8, 5, 4, 28, 11)

with (root / "def_layout.json").open(encoding="utf-8") as fh:
    layout = json.load(fh)
for key in ("fit_cadence_text", "fit_heart_rate_text"):
    if key in layout.get("indicators", {}):
        layout["indicators"][key]["enabled"] = args.charts >= (1 if key == "fit_cadence_text" else 2)

speed = smooth_speed_samples(tm.speed_samples, "moving_average", 5)
alt = smooth_speed_samples(tm.alt_samples, "moving_average", 5)
track = tm.track_samples
out = root / "Raporty" / "AMD_ETAP8B" / f"{args.tag}.mp4"
out.parent.mkdir(parents=True, exist_ok=True)
result = stream_overlay_to_ffmpeg(
    ffmpeg_exe=r"C:\tools\ffmpeg.exe",
    input_files=[str(root / "Video" / "GX030120.MP4")],
    output_file=str(out),
    duration_s=900 * (1001 / 30000),
    start_dt_utc=tm.start_dt_utc,
    tz_offset_hours=0.0,
    speed_samples=speed,
    track_samples=track,
    alt_samples=alt,
    font_path=resolve_font_path("Arial"),
    layout=layout,
    field_samples={"speed_samples": speed, "track_samples": track, "alt_samples": alt},
    max_distance_m=track[-1][1] if track else 0,
    target_fps=30000 / 1001,
    update_rate_step=1,
    workers=1,
    iso_samples=tm.iso_samples,
    exposure_samples=tm.exposure_samples,
    temperature_samples=tm.temperature_samples,
    fit_data=tm.fit_data,
    gps_track=tm.get_gps_track_for_source(layout.get("indicators", {}).get("track_map", {}).get("source", "fit")),
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
print(f"ETAP8B {args.tag} charts={args.charts} result={result}")
