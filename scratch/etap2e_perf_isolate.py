"""ETAP 2E perf isolation: above_compose cost attribution (120f runs).

Variants:
  base        - production config after fixes (lean live, gauge on GPU AUTO)
  no_lean     - lean_indicator disabled
  gauge_cpu   - AMD_GAUGE_PATH=CPU_REFERENCE (legacy pre-2D behaviour)
"""
from __future__ import annotations

import copy
import json
import os
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

VIDEO = Path("Video/GX030120.MP4")
FIT = Path("Video/Jazda_na_rowerze_w_porze_lunchu.fit")
OUT_DIR = Path("scratch/etap2e_isolate")
FRAMES = 120
FPS = 30000.0 / 1001.0


def build_env(variant: str) -> dict:
    env = dict(os.environ)
    env["AMD_NATIVE_DIAGNOSTICS"] = "0"
    if variant == "gauge_cpu":
        env["AMD_GAUGE_PATH"] = "CPU_REFERENCE"
    else:
        env.pop("AMD_GAUGE_PATH", None)
    return env


def run_variant(variant: str) -> None:
    code = f'''
import json, sys
from pathlib import Path
sys.path.insert(0, ".")
from src.gui.telemetry_manager import TelemetryDataManager
from src.telemetry_processed_cache import read_processed_cache, apply_processed_cache
from src.telemetry_extract import get_rotation_from_metadata, load_json_with_fallback, ensure_records_list
from src.ffmpeg.streaming import stream_overlay_to_ffmpeg

VIDEO = Path({str(VIDEO)!r})
FIT = Path({str(FIT)!r})
OUT_DIR = Path({str(OUT_DIR)!r})

layout = json.load(open("def_layout.json", encoding="utf-8"))
variant = "{variant}"
if variant == "no_lean":
    layout["indicators"]["lean_indicator"]["enabled"] = False

tm = TelemetryDataManager()
apply_processed_cache(tm, read_processed_cache(VIDEO))
records = ensure_records_list(load_json_with_fallback(VIDEO.with_suffix(".json")))
rot = get_rotation_from_metadata(records)
tm.load_fit(VIDEO, start_dt=tm.start_dt_utc, manual_path=FIT)

field_samples = {{
    "speed_samples": tm.speed_samples,
    "track_samples": tm.track_samples,
    "alt_samples": tm.alt_samples,
    "heading_samples": tm.heading_samples,
    "slope_samples": tm.slope_samples,
    "iso_samples": tm.iso_samples,
    "exposure_samples": tm.exposure_samples,
    "temperature_samples": tm.temperature_samples,
    "accel_x_samples": tm.accel_x_samples,
    "accel_y_samples": tm.accel_y_samples,
    "accel_z_samples": tm.accel_z_samples,
    "accel_magnitude_samples": tm.accel_magnitude_samples,
    "gyro_x_samples": tm.gyro_x_samples,
    "gyro_y_samples": tm.gyro_y_samples,
    "gyro_z_samples": tm.gyro_z_samples,
    "gyro_magnitude_samples": tm.gyro_magnitude_samples,
}}

stream_overlay_to_ffmpeg(
    ffmpeg_exe=r"C:\\tools\\ffmpeg.exe",
    input_files=[str(VIDEO)],
    output_file=str(OUT_DIR / ("out_" + variant + ".mp4")),
    duration_s={FRAMES} / {FPS:.6f},
    start_dt_utc=tm.start_dt_utc,
    tz_offset_hours=2,
    speed_samples=tm.speed_samples,
    track_samples=tm.track_samples,
    alt_samples=tm.alt_samples,
    font_path="arial.ttf",
    layout=layout,
    field_samples=field_samples,
    target_fps={FPS:.6f},
    workers=4,
    iso_samples=tm.iso_samples,
    exposure_samples=tm.exposure_samples,
    temperature_samples=tm.temperature_samples,
    fit_data=tm.fit_data,
    gps_track=tm.get_gps_track_for_source("fit"),
    encoder="amd",
    video_bitrate="40M",
    render_w=3840, render_h=2160,
    resolution_name="source",
    rotation_degrees=rot, container_rotation=0,
    overlay_w=3840, overlay_h=2160,
)
'''
    proc = subprocess.run(
        [sys.executable, "-c", code], env=build_env(variant),
        capture_output=True, text=True, cwd=".",
    )
    tail = proc.stdout.strip().splitlines()[-3:] if proc.stdout else []
    prof_path = OUT_DIR / ("out_" + variant + ".mp4.amd_profile.json")
    if prof_path.exists():
        prof = json.load(open(prof_path, encoding="utf-8"))
        t = prof.get("timings", {})
        p8 = prof.get("etap8p_a", {})
        e5l = prof.get("etap5l", {})
        ac = t.get("above_compose", {}).get("avg_ms")
        at = t.get("above_total", {}).get("avg_ms")
        pp = t.get("producer_prepare", {}).get("avg_ms")
        print(
            f"[{variant:>10}] above_compose={ac:7.2f} above_total={at:7.2f} "
            f"producer={pp:7.2f} render_fps={p8.get('render_fps')} "
            f"gauge_gpu={e5l.get('gauge_gpu_active')} frames={e5l.get('gauge_gpu_frames')}"
        )
    else:
        print(f"[{variant}] NO PROFILE; tail={tail}")
        if proc.returncode != 0:
            print(proc.stderr[-1500:])


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for variant in ("base", "no_lean", "gauge_cpu"):
        run_variant(variant)


if __name__ == "__main__":
    main()
