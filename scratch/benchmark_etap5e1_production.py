"""Three preview-ON NVIDIA exports for ETAP 5E.1."""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scratch.benchmark_etap5b6_production import prepare
from src.ffmpeg.streaming import stream_overlay_to_ffmpeg


VIDEO = ROOT / "Video" / "GX030120.MP4"
FPS = 30000 / 1001


def main():
    samples, anchor, fit, layout = prepare()
    results = []
    for run_no in range(1, 4):
        preview_events = []
        last_ts = -1.0

        def on_progress(done, total, elapsed, pipeline_fps, hud_state):
            nonlocal last_ts
            if hud_state is not None and hud_state.get("ts", -1.0) - last_ts >= 0.2:
                preview_events.append(hud_state)
                last_ts = hud_state["ts"]

        output = ROOT / "scratch" / f"etap5e1_production_run{run_no}.mp4"
        started = time.perf_counter()
        stream_overlay_to_ffmpeg(
            ffmpeg_exe="ffmpeg", input_files=[str(VIDEO)], output_file=str(output),
            duration_s=5400 / FPS, start_dt_utc=anchor, tz_offset_hours=2,
            speed_samples=samples["speed"], track_samples=samples["track"],
            alt_samples=samples["alt"], font_path="", layout=layout,
            field_samples={"start_dt_utc": anchor, "speed_samples": samples["speed"],
                           "track_samples": samples["track"], "alt_samples": samples["alt"],
                           "iso_samples": samples["iso"], "exposure_samples": samples["exposure"],
                           "temp_samples": samples["temp"]},
            max_distance_m=samples["track"][-1][1] if samples["track"] else 0,
            target_fps=FPS, update_rate_step=1, workers=4,
            iso_samples=samples["iso"], exposure_samples=samples["exposure"],
            temperature_samples=samples["temp"], fit_data=fit, gps_track=fit.get("track"),
            encoder="nv", gpu=0, video_bitrate="40M", render_w=3840, render_h=2160,
            resolution_name="source", rotation_degrees=0, container_rotation=0,
            overlay_w=1920, overlay_h=1080, on_render_progress=on_progress,
        )
        wall = time.perf_counter() - started
        result = {
            "run": run_no, "wall_s": wall, "real_export_fps": 5400 / wall,
            "preview_updates": len(preview_events),
            "preview_fps": len(preview_events) / wall,
        }
        results.append(result)
        print(result, flush=True)
    destination = ROOT / "scratch" / "etap5e1_production_results.json"
    destination.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(json.dumps(results, indent=2), flush=True)


if __name__ == "__main__":
    main()
