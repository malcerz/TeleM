import sys, subprocess
from pathlib import Path
_root = Path(__file__).resolve().parent.parent
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

import numpy as np
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
from src.ffmpeg.command_builder import _build_stream_ffmpeg_cmd, get_layout_hud_regions

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

    field_samples = {
        "speed_samples": speed_samples,
        "track_samples": track_samples,
        "alt_samples": alt_samples,
        "iso_samples": iso_samples,
        "exposure_samples": exposure_samples,
        "temperature_samples": temp_samples,
    }

    test_layout = normalize_layout("def_layout.json", 1920, 1080)
    for k, v in list(test_layout["indicators"].items()):
        if k not in ("time_block", "fit_cadence_text", "fit_enhanced_speed_text", "fit_heart_rate_text"):
            v["enabled"] = False

    out_atlas = Path('scratch/parity_true_atlas.mp4')
    out_full = Path('scratch/parity_true_full.mp4')

    print("1. Renderowanie MULTI-REGION ATLAS...")
    stream_overlay_to_ffmpeg(
        ffmpeg_exe="ffmpeg", input_files=[str(v_file)], output_file=str(out_atlas),
        duration_s=37.74, start_dt_utc=anchor_dt, tz_offset_hours=0.0,
        speed_samples=speed_samples, track_samples=track_samples, alt_samples=alt_samples,
        font_path="", layout=test_layout, field_samples=field_samples, target_fps=29.97,
        update_rate_step=1, workers=4, encoder="nv", gpu=0, video_bitrate="40M",
        render_w=3840, render_h=2160, resolution_name="source", rotation_degrees=0,
        container_rotation=0, overlay_w=1920, overlay_h=1080,
        iso_samples=iso_samples, exposure_samples=exposure_samples, temperature_samples=temp_samples,
        fit_data=fit_data, gps_track=fit_data.get("track"),
    )

    print("\n2. Renderowanie TRUE FULL-FRAME REFERENCE...")
    layout_full_forced = normalize_layout("def_layout.json", 1920, 1080)
    for k, v in list(layout_full_forced["indicators"].items()):
        if k not in ("time_block", "fit_cadence_text", "fit_enhanced_speed_text", "fit_heart_rate_text"):
            v["enabled"] = False
    layout_full_forced["indicators"]["_c1"] = {"enabled": True, "x": 0.0, "y": 0.0, "form": "text", "size": 0.01}
    layout_full_forced["indicators"]["_c2"] = {"enabled": True, "x": 99.0, "y": 0.0, "form": "text", "size": 0.01}
    layout_full_forced["indicators"]["_c3"] = {"enabled": True, "x": 0.0, "y": 99.0, "form": "text", "size": 0.01}
    layout_full_forced["indicators"]["_c4"] = {"enabled": True, "x": 99.0, "y": 99.0, "form": "text", "size": 0.01}

    stream_overlay_to_ffmpeg(
        ffmpeg_exe="ffmpeg", input_files=[str(v_file)], output_file=str(out_full),
        duration_s=37.74, start_dt_utc=anchor_dt, tz_offset_hours=0.0,
        speed_samples=speed_samples, track_samples=track_samples, alt_samples=alt_samples,
        font_path="", layout=layout_full_forced, field_samples=field_samples, target_fps=29.97,
        update_rate_step=1, workers=4, encoder="nv", gpu=0, video_bitrate="40M",
        render_w=3840, render_h=2160, resolution_name="source", rotation_degrees=0,
        container_rotation=0, overlay_w=1920, overlay_h=1080,
        iso_samples=iso_samples, exposure_samples=exposure_samples, temperature_samples=temp_samples,
        fit_data=fit_data, gps_track=fit_data.get("track"),
    )

    timestamps = [
        ("0% (Początek)", 0.0),
        ("25%", 9.4),
        ("50% (Środek)", 18.8),
        ("75%", 28.3),
        ("100% (Koniec)", 37.0),
    ]

    print("\n--- PORÓWNANIE PIXEL PARITY (TRUE FULL FRAME VS MULTI-REGION ATLAS) ---")
    for name, ts in timestamps:
        p_atlas = Path(f"scratch/frame_true_atlas_{ts:.1f}.png")
        p_full = Path(f"scratch/frame_true_full_{ts:.1f}.png")
        subprocess.run(["ffmpeg", "-y", "-ss", str(ts), "-i", str(out_atlas), "-vframes", "1", str(p_atlas)], check=True, capture_output=True)
        subprocess.run(["ffmpeg", "-y", "-ss", str(ts), "-i", str(out_full), "-vframes", "1", str(p_full)], check=True, capture_output=True)

        arr_a = np.asarray(Image.open(p_atlas))
        arr_f = np.asarray(Image.open(p_full))
        diff = np.abs(arr_a.astype(int) - arr_f.astype(int))
        max_d = int(np.max(diff))
        mean_d = float(np.mean(diff))
        diff_px = int(np.count_nonzero(diff.any(axis=-1)))
        total_px = arr_a.shape[0] * arr_a.shape[1]
        pct = diff_px / total_px * 100.0
        print(f"[{name:15s} t={ts:4.1f}s] Max diff: {max_d:3d} | Mean diff: {mean_d:.4f} | Diff px: {diff_px:7d}/{total_px} ({pct:5.2f}%)")

if __name__ == "__main__":
    main()
