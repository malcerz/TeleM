import sys, os, time
from pathlib import Path
_root = Path(__file__).resolve().parent.parent
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

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

    duration_s = 37.74
    target_fps = 29.97

    # Sub-window layout: Speed Gauge + Speed Text + Dist Text + Alt Text (Bottom Center HUD)
    # Bbox: ~900x400 px -> ~18% area
    sub_layout = normalize_layout(None, 1920, 1080)
    for k, v in sub_layout["indicators"].items():
        if k not in ("speed_visual", "speed_text", "dist_text", "alt_text"):
            v["enabled"] = False

    out_bbox = Path('scratch/bench_sub_bbox.mp4')
    print("\n--- Sub-Window HUD Layout with Active HUD Bbox ---")
    t0 = time.perf_counter()
    n_bbox = stream_overlay_to_ffmpeg(
        ffmpeg_exe="ffmpeg",
        input_files=[str(v_file)],
        output_file=str(out_bbox),
        duration_s=duration_s,
        start_dt_utc=anchor_dt,
        tz_offset_hours=0.0,
        speed_samples=speed_samples,
        track_samples=track_samples,
        alt_samples=alt_samples,
        font_path="",
        layout=sub_layout,
        field_samples={},
        target_fps=target_fps,
        update_rate_step=1,
        workers=4,
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
    elapsed_bbox = t1 - t0
    fps_bbox = n_bbox / elapsed_bbox
    print(f"[RESULT SUB-WINDOW] Elapsed: {elapsed_bbox:.2f} s | FPS: {fps_bbox:.2f} FPS")

if __name__ == '__main__':
    main()
