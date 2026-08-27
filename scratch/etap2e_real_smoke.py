"""ETAP 2E — real-project AMD smoke (300 frames, GX030120 + def_layout.json).

Runs the production stream_overlay_to_ffmpeg pipeline with the same parameter
set the GUI render path uses, then prints the GPU activation evidence from
console + amd_profile JSON.
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

os.environ.setdefault("AMD_NATIVE_DIAGNOSTICS", "1")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.gui.telemetry_manager import TelemetryDataManager
from src.telemetry_processed_cache import read_processed_cache, apply_processed_cache
from src.telemetry_extract import (
    get_rotation_from_metadata,
    load_json_with_fallback,
    ensure_records_list,
)
from src.ffmpeg.streaming import stream_overlay_to_ffmpeg

VIDEO = Path("Video/GX030120.MP4")
FIT = Path("Video/Jazda_na_rowerze_w_porze_lunchu.fit")
OUT_DIR = Path("scratch/etap2e_smoke")
FRAMES = 300
FPS = 30000.0 / 1001.0


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    layout = json.load(open("def_layout.json", encoding="utf-8"))

    tm = TelemetryDataManager()
    processed = read_processed_cache(VIDEO)
    assert processed is not None, "processed cache missing"
    apply_processed_cache(tm, processed)

    records = ensure_records_list(
        load_json_with_fallback(VIDEO.with_suffix(".json"))
    )
    rotation_degrees = get_rotation_from_metadata(records)
    print(f"source rotation metadata = {rotation_degrees}")

    fit_ok = tm.load_fit(VIDEO, start_dt=tm.start_dt_utc, manual_path=FIT)
    print(f"FIT loaded: {fit_ok}; fields={sorted(tm.fit_data.keys())}")

    field_samples = {
        "speed_samples": tm.speed_samples,
        "track_samples": tm.track_samples,
        "alt_samples": tm.alt_samples,
        "heading_samples": tm.heading_samples,
        "gpx_heading_samples": tm.gpx_heading_samples,
        "slope_samples": tm.slope_samples,
        "gpx_slope_samples": tm.gpx_slope_samples,
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
    }

    t0 = time.perf_counter()
    total = stream_overlay_to_ffmpeg(
        ffmpeg_exe=r"C:\tools\ffmpeg.exe",
        input_files=[str(VIDEO)],
        output_file=str(OUT_DIR / "out_300f.mp4"),
        duration_s=FRAMES / FPS,
        start_dt_utc=tm.start_dt_utc,
        tz_offset_hours=2,
        speed_samples=tm.speed_samples,
        track_samples=tm.track_samples,
        alt_samples=tm.alt_samples,
        font_path="arial.ttf",
        layout=layout,
        field_samples=field_samples,
        max_distance_m=(tm.track_samples[-1][1] if tm.track_samples else 0),
        target_fps=FPS,
        workers=4,
        iso_samples=tm.iso_samples,
        exposure_samples=tm.exposure_samples,
        temperature_samples=tm.temperature_samples,
        gpx_speed_samples=tm.gpx_speed_samples,
        gpx_track_samples=tm.gpx_track_samples,
        gpx_alt_samples=tm.gpx_alt_samples,
        fit_data=tm.fit_data,
        gps_track=tm.get_gps_track_for_source(
            layout.get("indicators", {}).get("track_map", {}).get("source", "fit")
        ),
        encoder="amd",
        video_bitrate="40M",
        render_w=3840,
        render_h=2160,
        resolution_name="source",
        rotation_degrees=rotation_degrees,
        container_rotation=0,
        overlay_w=3840,
        overlay_h=2160,
    )
    wall = time.perf_counter() - t0
    print(f"\n[SMOKE] piped frames={total} wall={wall:.2f}s render_fps={total / wall:.3f}")

    prof_path = OUT_DIR / "out_300f.mp4.amd_profile.json"
    if prof_path.exists():
        prof = json.load(open(prof_path, encoding="utf-8"))
        e5l = prof.get("etap5l", {})
        e5g = prof.get("etap5g", {})
        fa = prof.get("frame_accounting", {})
        p8p = prof.get("etap8p_a", {})
        print("[SMOKE] etap5l gauge:", {
            k: e5l.get(k) for k in (
                "gauge_gpu_active", "gauge_gpu_frames",
                "etap2b_gauge_region_upload_frames",
                "etap2b_gauge_full_upload_frames",
            )
        })
        print("[SMOKE] etap5g map:", {
            k: e5g.get(k) for k in ("map_order", "map_above_visible_frames")
        })
        print("[SMOKE] frame_accounting:", {
            k: fa.get(k) for k in ("muxed_frames",)
        })
        print("[SMOKE] perf:", {
            k: p8p.get(k) for k in ("render_fps", "effective_fps",
                                    "delay_export_to_first_frame_ms")
        })


if __name__ == "__main__":
    main()
