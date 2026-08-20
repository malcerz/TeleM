import sys, os, time, math
from pathlib import Path
_root = Path(__file__).resolve().parent.parent
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))
from datetime import datetime, timezone

from telemetry_fit import process_fit
from src.gui.layout_manager import normalize_layout
from src.telemetry_gpmf_new import gpmf_to_exiftool_json
from src.telemetry_extract import (
    extract_speed_samples, extract_altitude_samples, extract_track_samples,
    extract_iso_samples, extract_exposure_samples, extract_temperature_samples,
    find_gps_anchor
)
from src.ffmpeg.streaming import stream_overlay_to_ffmpeg

def main():
    v_file = Path('Video/GX020079.mp4')
    fit_file = Path('Video/Morning_Ride.fit')
    out_file = Path('scratch/test_nv_workers_out.mp4')

    print(f"[TEST] Extracting telemetry from {v_file}...")
    records = gpmf_to_exiftool_json(str(v_file))[0]
    speed_samples = extract_speed_samples(records)
    alt_samples = extract_altitude_samples(records)
    track_samples = extract_track_samples(records)
    iso_samples = extract_iso_samples(records)
    exposure_samples = extract_exposure_samples(records)
    temp_samples = extract_temperature_samples(records)
    anchor_dt = find_gps_anchor(records)

    fit_data = process_fit(str(fit_file), video_start_dt=anchor_dt)
    layout = normalize_layout(None, 1920, 1080)

    # Full duration test (37.74s, 1131 frames at 29.97 FPS)
    duration_s = 37.74
    target_fps = 29.97

    progress_records = []
    def progress_cb(frame, stats):
        progress_records.append((time.time(), frame, stats))
        if frame % 100 == 0 or frame == 1131:
            print(f"  {stats}", flush=True)

    print(f"\n[TEST] Starting NVIDIA full export test (automatic workers)...", flush=True)
    t0 = time.perf_counter()
    total_frames = stream_overlay_to_ffmpeg(
        ffmpeg_exe="ffmpeg",
        input_files=[str(v_file)],
        output_file=str(out_file),
        duration_s=duration_s,
        start_dt_utc=anchor_dt,
        tz_offset_hours=0.0,
        speed_samples=speed_samples,
        track_samples=track_samples,
        alt_samples=alt_samples,
        font_path="",
        layout=layout,
        field_samples={},
        target_fps=target_fps,
        update_rate_step=1,
        workers=None,  # Automatic default (4 for NVIDIA)
        encoder="nv",
        gpu=0,
        video_bitrate="40M",
        render_w=3840,
        render_h=2160,
        resolution_name="source",
        rotation_degrees=0,
        container_rotation=0,
        overlay_w=1920,
        overlay_h=1080,
        iso_samples=iso_samples,
        exposure_samples=exposure_samples,
        temperature_samples=temp_samples,
        fit_data=fit_data,
        gps_track=fit_data.get("track"),
        progress_cb=progress_cb,
    )
    t1 = time.perf_counter()
    elapsed = t1 - t0
    fps = total_frames / elapsed

    print(f"\n[TEST RESULT] Export finished successfully!", flush=True)
    print(f"  Total Frames: {total_frames}", flush=True)
    print(f"  Elapsed Time: {elapsed:.2f} s", flush=True)
    print(f"  Effective FPS: {fps:.2f} FPS", flush=True)
    print(f"  Output exists: {out_file.exists()} (size: {out_file.stat().st_size / (1024*1024):.1f} MB)", flush=True)

if __name__ == '__main__':
    main()
