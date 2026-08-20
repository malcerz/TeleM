from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
VIDEO = ROOT / "Video" / "GX030120.MP4"
FIT_PATH = ROOT / "Video" / "Popoludniowa_jazda_na_rowerze_solar_battery.fit"

from telemetry_fit import process_fit
from src.gui.layout_manager import normalize_layout
from src.telemetry_gpmf_new import gpmf_to_exiftool_json
from src.telemetry_extract import (
    extract_altitude_samples, extract_exposure_samples, extract_iso_samples,
    extract_speed_samples, extract_temperature_samples, extract_track_samples,
    find_gps_anchor,
)
from src.ffmpeg.streaming import stream_overlay_to_ffmpeg


def main():
    records = gpmf_to_exiftool_json(str(VIDEO))[0]
    speed = extract_speed_samples(records)
    alt = extract_altitude_samples(records)
    track = extract_track_samples(records)
    iso = extract_iso_samples(records)
    exposure = extract_exposure_samples(records)
    temp = extract_temperature_samples(records)
    anchor = find_gps_anchor(records)
    fit = process_fit(str(FIT_PATH), video_start_dt=anchor)
    layout = normalize_layout(ROOT / "def_layout.json", 1920, 1080)
    fps = 30000 / 1001
    duration = 5400 / fps
    results = []
    for run in range(1, 4):
        output = ROOT / "scratch" / f"nvidia_regression_preview_run{run}.mp4"
        preview_events = []
        last_preview = -1.0

        def on_progress(done, total, elapsed, pipeline_fps, hud_state):
            nonlocal last_preview
            if hud_state is not None and hud_state.get("ts", -1.0) - last_preview >= 0.2:
                preview_events.append((time.perf_counter(), hud_state["frame"], hud_state["ts"]))
                last_preview = hud_state["ts"]

        t0 = time.perf_counter()
        stream_overlay_to_ffmpeg(
            ffmpeg_exe="ffmpeg", input_files=[str(VIDEO)], output_file=str(output), duration_s=duration,
            start_dt_utc=anchor, tz_offset_hours=2, speed_samples=speed, track_samples=track,
            alt_samples=alt, font_path="", layout=layout,
            field_samples={"start_dt_utc": anchor, "speed_samples": speed, "track_samples": track,
                           "alt_samples": alt, "iso_samples": iso, "exposure_samples": exposure,
                           "temp_samples": temp},
            max_distance_m=track[-1][1] if track else 0, target_fps=fps, update_rate_step=1,
            workers=4, iso_samples=iso, exposure_samples=exposure, temperature_samples=temp,
            fit_data=fit, gps_track=fit.get("track"), encoder="nv", gpu=0, video_bitrate="40M",
            render_w=3840, render_h=2160, resolution_name="source", rotation_degrees=0,
            container_rotation=0, overlay_w=1920, overlay_h=1080,
            on_render_progress=on_progress,
        )
        wall = time.perf_counter() - t0
        results.append({"run": run, "wall_s": wall, "real_export_fps": 5400 / wall,
                        "preview_updates": len(preview_events),
                        "preview_fps": len(preview_events) / wall if wall else 0,
                        "first_preview": preview_events[0] if preview_events else None})
        print(results[-1], flush=True)
    print({"runs": results, "median_real_export_fps": sorted(r["real_export_fps"] for r in results)[1]}, flush=True)


if __name__ == "__main__":
    main()
