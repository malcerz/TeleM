import sys, time
from pathlib import Path
_root = Path(__file__).resolve().parent.parent
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

from PIL import Image
from telemetry_fit import process_fit
from src.gui.layout_manager import normalize_layout
from src.telemetry_gpmf_new import gpmf_to_exiftool_json
from src.telemetry_extract import (
    extract_speed_samples, extract_altitude_samples, extract_track_samples,
    extract_iso_samples, extract_exposure_samples, extract_temperature_samples,
    find_gps_anchor
)
from src.ffmpeg.streaming import stream_overlay_to_ffmpeg
from src.indicators.compositor import render_preview

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

    print("\n--- 1. Testing render_preview with default layout (alt_visual + dist_visual) ---")
    base_img = Image.new("RGBA", (1920, 1080), (20, 20, 20, 255))
    t0 = time.perf_counter()
    preview_img = render_preview(
        src_img=base_img, layout=layout, font_path="",
        date_text="2026-08-20", time_text="12:00:00",
        speed_value=25.4, distance_m=5420.0, max_distance_m=10000.0,
        alt_value=145.0, min_alt=50.0, max_alt=300.0,
        iso_value=100.0, exposure_value=500.0, temp_value=25.0,
    )
    t1 = time.perf_counter()
    print(f"render_preview completed in {(t1 - t0)*1000:.2f} ms")
    assert preview_img is not None
    preview_img.save("scratch/preview_bar_integration.png")

    print("\n--- 2. Testing 2-second streaming export with unified bar.py ---")
    out_video = Path("scratch/test_bar_stream.mp4")
    t0 = time.perf_counter()
    n_frames = stream_overlay_to_ffmpeg(
        ffmpeg_exe="ffmpeg",
        input_files=[str(v_file)],
        output_file=str(out_video),
        duration_s=2.0,
        start_dt_utc=anchor_dt,
        tz_offset_hours=0.0,
        speed_samples=speed_samples,
        track_samples=track_samples,
        alt_samples=alt_samples,
        font_path="",
        layout=layout,
        field_samples={},
        target_fps=29.97,
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
    print(f"Exported {n_frames} frames in {t1 - t0:.2f} s ({n_frames/(t1 - t0):.2f} FPS)")

    print("\nALL PREVIEW AND STREAMING VERIFICATIONS SUCCESSFUL!")

if __name__ == "__main__":
    main()
