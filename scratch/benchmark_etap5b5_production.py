from __future__ import annotations

import subprocess
import time
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
VIDEO = ROOT / "Video" / "GX030120.MP4"
FIT_PATH = ROOT / "Video" / "Poranna_jazda_na_rowerze.fit"

from telemetry_fit import process_fit
from src.gui.layout_manager import normalize_layout
from src.telemetry_gpmf_new import gpmf_to_exiftool_json
from src.telemetry_extract import extract_altitude_samples, extract_exposure_samples, extract_iso_samples, extract_speed_samples, extract_temperature_samples, extract_track_samples, find_gps_anchor
from src.ffmpeg.streaming import stream_overlay_to_ffmpeg


def main():
    records = gpmf_to_exiftool_json(str(VIDEO))[0]
    speed = extract_speed_samples(records); alt = extract_altitude_samples(records); track = extract_track_samples(records)
    iso = extract_iso_samples(records); exposure = extract_exposure_samples(records); temp = extract_temperature_samples(records)
    anchor = find_gps_anchor(records)
    fit = process_fit(str(FIT_PATH), video_start_dt=anchor)
    layout = normalize_layout(ROOT / "def_layout.json", 1920, 1080)
    duration = 5400 / (30000 / 1001)
    results = []
    for run in range(1, 4):
        output = ROOT / "scratch" / f"etap5b5_production_run{run}.mp4"
        t0 = time.perf_counter()
        print(f"=== PRODUCTION RUN {run} ===", flush=True)
        stream_overlay_to_ffmpeg(
            ffmpeg_exe="ffmpeg", input_files=[str(VIDEO)], output_file=str(output), duration_s=duration,
            start_dt_utc=anchor, tz_offset_hours=2, speed_samples=speed, track_samples=track, alt_samples=alt,
            font_path="", layout=layout, field_samples={"start_dt_utc": anchor, "speed_samples": speed, "track_samples": track, "alt_samples": alt, "iso_samples": iso, "exposure_samples": exposure, "temp_samples": temp},
            max_distance_m=track[-1][1] if track else 0, target_fps=30000/1001, update_rate_step=1, workers=4,
            iso_samples=iso, exposure_samples=exposure, temperature_samples=temp, fit_data=fit, gps_track=fit.get("track"),
            encoder="nv", gpu=0, video_bitrate="40M", render_w=3840, render_h=2160, resolution_name="source",
            rotation_degrees=0, container_rotation=0, overlay_w=1920, overlay_h=1080,
        )
        elapsed = time.perf_counter() - t0
        results.append({"run": run, "wall_elapsed_s": elapsed, "output": str(output)})
        print(f"=== RUN {run} WALL {elapsed:.3f}s ===", flush=True)
    print(results)


if __name__ == "__main__": main()
