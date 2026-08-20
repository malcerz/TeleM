import sys, os, time
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

    duration_s = 10.0  # 300 frames
    target_fps = 29.97

    print(f"\n{'Wariant':12s} | {'Workers':8s} | {'In-flight':10s} | {'SHM (MB)':10s} | {'Czas (s)':10s} | {'FPS':10s}")
    print("-" * 72)

    for w in [2, 4, 6, 8, 31]:
        out_p = f"scratch/bench_w{w}.mp4"
        t0 = time.perf_counter()
        total_frames = stream_overlay_to_ffmpeg(
            ffmpeg_exe="ffmpeg",
            input_files=[str(v_file)],
            output_file=out_p,
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
            workers=w,
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
        )
        t1 = time.perf_counter()
        elapsed = t1 - t0
        fps = total_frames / elapsed
        slots = max(4, w * 2)
        shm_mb = slots * 7.91
        w_label = "default (po)" if w == 4 else ("stary (przed)" if w == 31 else f"{w}W")
        print(f"{w_label:12s} | {w:8d} | {slots:10d} | {shm_mb:10.1f} | {elapsed:10.2f} | {fps:10.2f}")
        try:
            Path(out_p).unlink(missing_ok=True)
        except Exception:
            pass

if __name__ == '__main__':
    main()
