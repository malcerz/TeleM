from __future__ import annotations

import json
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


def prepare():
    records = gpmf_to_exiftool_json(str(VIDEO))[0]
    samples = {
        "speed": extract_speed_samples(records), "alt": extract_altitude_samples(records),
        "track": extract_track_samples(records), "iso": extract_iso_samples(records),
        "exposure": extract_exposure_samples(records), "temp": extract_temperature_samples(records),
    }
    anchor = find_gps_anchor(records)
    fit = process_fit(str(FIT_PATH), video_start_dt=anchor)
    return samples, anchor, fit, normalize_layout(str(ROOT / "def_layout.json"), 1920, 1080)


def run(mode, samples, anchor, fit, layout, run_no):
    fps = 30000 / 1001
    preview_events = []
    last_preview = -1.0

    def on_progress(done, total, elapsed, pipeline_fps, hud_state):
        nonlocal last_preview
        if hud_state is not None and hud_state.get("ts", -1.0) - last_preview >= 0.2:
            preview_events.append((hud_state["frame"], hud_state["ts"]))
            last_preview = hud_state["ts"]

    output = ROOT / "scratch" / f"etap5b6_{mode}_run{run_no}.mp4"
    t0 = time.perf_counter()
    stream_overlay_to_ffmpeg(
        ffmpeg_exe="ffmpeg", input_files=[str(VIDEO)], output_file=str(output), duration_s=5400 / fps,
        start_dt_utc=anchor, tz_offset_hours=2, speed_samples=samples["speed"],
        track_samples=samples["track"], alt_samples=samples["alt"], font_path="", layout=layout,
        field_samples={"start_dt_utc": anchor, "speed_samples": samples["speed"],
                       "track_samples": samples["track"], "alt_samples": samples["alt"],
                       "iso_samples": samples["iso"], "exposure_samples": samples["exposure"],
                       "temp_samples": samples["temp"]},
        max_distance_m=samples["track"][-1][1] if samples["track"] else 0,
        target_fps=fps, update_rate_step=1, workers=4,
        iso_samples=samples["iso"], exposure_samples=samples["exposure"],
        temperature_samples=samples["temp"], fit_data=fit, gps_track=fit.get("track"),
        encoder="nv", gpu=0, video_bitrate="40M", render_w=3840, render_h=2160,
        resolution_name="source", rotation_degrees=0, container_rotation=0,
        overlay_w=1920, overlay_h=1080,
        on_render_progress=on_progress if mode == "on" else None,
    )
    wall = time.perf_counter() - t0
    item = {"mode": mode, "run": run_no, "wall_s": wall, "real_export_fps": 5400 / wall,
            "preview_updates": len(preview_events),
            "preview_fps": len(preview_events) / wall if wall else 0}
    print(item, flush=True)
    return item


def main():
    samples, anchor, fit, layout = prepare()
    results = []
    for mode in ("off", "on"):
        for run_no in range(1, 4):
            results.append(run(mode, samples, anchor, fit, layout, run_no))
    (ROOT / "scratch" / "etap5b6_production_results.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(results, flush=True)


if __name__ == "__main__":
    main()
