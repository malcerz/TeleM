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
OUT_DIR = Path("scratch/etap2f_bench")
FRAMES = 300
FPS = 30000.0 / 1001.0

def main():
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
    fit_ok = tm.load_fit(VIDEO, start_dt=tm.start_dt_utc, manual_path=FIT)

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

    out_file = str(OUT_DIR / "cand_300f.mp4")
    if Path(out_file).exists():
        Path(out_file).unlink()
    profile_path = Path(out_file + ".amd_profile.json")
    if profile_path.exists():
        profile_path.unlink()

    t0 = time.perf_counter()
    total = stream_overlay_to_ffmpeg(
        ffmpeg_exe=r"C:\tools\ffmpeg.exe",
        input_files=[str(VIDEO)],
        output_file=out_file,
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
    t1 = time.perf_counter()
    wall = t1 - t0
    fps = total / wall if wall > 0 else 0
    print(f"\nRENDER DONE: {total} frames in {wall:.2f} s -> {fps:.2f} FPS")

    if profile_path.exists():
        prof = json.load(open(profile_path, encoding="utf-8"))
        print("\n--- AMD PROFILE SUMMARY ---")
        fa = prof.get("frame_accounting", {})
        p8p = prof.get("etap8p_a", {})
        times = prof.get("times", {})
        print(f"RENDER FPS:          {prof.get('render_fps', p8p.get('render_fps', 0)):.3f}")
        print(f"above_compose avg:   {prof.get('above_compose_ms_avg', times.get('above_compose_avg', 0)):.3f} ms")
        print(f"above_total avg:     {prof.get('above_total_ms_avg', times.get('above_total_avg', 0)):.3f} ms")
        print(f"producer_prepare:    {prof.get('producer_prepare_ms_avg', times.get('producer_prepare_avg', 0)):.3f} ms")
        print(f"consumer_native:     {prof.get('consumer_native_call_ms_avg', times.get('consumer_native_call_avg', 0)):.3f} ms")
        print(f"pipeline_total:      {prof.get('pipeline_total_ms_avg', times.get('pipeline_total_avg', 0)):.3f} ms")

if __name__ == "__main__":
    main()
