"""Render baseline frames for pixel parity comparison before ETAP 1A changes."""
import json
import os
import sys
import subprocess
from pathlib import Path
import numpy as np
from PIL import Image

root = Path("c:/_DEV/TeleM")
sys.path.insert(0, str(root))

from src.gui.telemetry_manager import TelemetryDataManager
from src.telemetry_extract import (
    ensure_records_list, load_json_with_fallback,
    extract_speed_samples, extract_altitude_samples, extract_track_samples,
    extract_iso_samples, extract_exposure_samples, extract_temperature_samples,
    smooth_speed_samples, interpolate_value, get_rotation_from_metadata,
    get_container_rotation, find_metadata_json, extract_gps_track,
    smooth_speed_values, extract_accelerometer_samples, extract_gyroscope_samples,
)
from src.ffmpeg.amd_native_exporter import export_amd_native_d3d11

VIDEO = root / "Video" / "GX010115.MP4"
META = root / "Video" / "GX010115.json"
FIT = root / "Video" / "Jazda_na_rowerze_w_porze_lunchu.fit"
LAYOUT_PATH = root / "presets" / "cycling_dashboard_v10.json"
OUT_DIR = root / "scratch" / "parity_test"
OUT_DIR.mkdir(parents=True, exist_ok=True)

def load_data():
    with open(LAYOUT_PATH, "r", encoding="utf-8") as f:
        layout = json.load(f)
    telemetry = TelemetryDataManager(
        extract_speed_fn=extract_speed_samples,
        extract_altitude_fn=extract_altitude_samples,
        extract_track_fn=extract_track_samples,
        extract_iso_fn=extract_iso_samples,
        extract_exposure_fn=extract_exposure_samples,
        extract_temperature_fn=extract_temperature_samples,
        smooth_fn=smooth_speed_samples,
        interpolate_fn=interpolate_value,
        get_rotation_meta_fn=get_rotation_from_metadata,
        get_container_rotation_fn=get_container_rotation,
        find_meta_json_fn=find_metadata_json,
        find_meta_json_write_fn=lambda p: p.with_suffix(".json"),
        load_telemetry_fn=lambda *a: None,
        ensure_records_fn=ensure_records_list,
        load_json_fallback_fn=load_json_with_fallback,
        write_records_fn=lambda p, r: None,
        extract_samples_exiftool_fn=lambda f: [],
        extract_altitude_exiftool_fn=lambda f: [],
        extract_gps_track_fn=extract_gps_track,
        find_gps_anchor_fn=lambda r: None,
        smooth_values_fn=smooth_speed_values,
        extract_accelerometer_fn=extract_accelerometer_samples,
        extract_gyroscope_fn=extract_gyroscope_samples,
    )
    with open(META, "r", encoding="utf-8") as f:
        meta = json.load(f)
    records = ensure_records_list(meta)
    telemetry.load_gpmf_records(records)
    telemetry.load_gps_track(records)
    telemetry.load_fit(VIDEO, telemetry.start_dt_utc, manual_path=FIT)
    return layout, telemetry

def extract_frames_from_video(mp4_path, out_prefix, frame_indices=[5, 15, 25]):
    out_paths = []
    for idx in frame_indices:
        out_png = OUT_DIR / f"{out_prefix}_f{idx:03d}.png"
        # Extract specific frame using ffmpeg
        pts_time = idx / 60.0
        cmd = [
            "ffmpeg", "-y", "-ss", f"{pts_time:.4f}", "-i", str(mp4_path),
            "-frames:v", "1", str(out_png)
        ]
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
        out_paths.append(out_png)
    return out_paths

def main():
    layout, telemetry = load_data()
    out_mp4 = OUT_DIR / "baseline_ref.mp4"
    if out_mp4.exists():
        out_mp4.unlink()
    
    print("[PARITY] Rendering 30 baseline frames (0.5s) with full preset v10...")
    ok = export_amd_native_d3d11(
        ffmpeg_exe="ffmpeg",
        input_files=[str(VIDEO)],
        output_file=str(out_mp4),
        duration_s=0.5,
        video_width=1920,
        video_height=1080,
        start_dt_utc=telemetry.start_dt_utc,
        tz_offset_hours=2.0,
        speed_samples=telemetry.speed_samples,
        track_samples=telemetry.track_samples,
        alt_samples=telemetry.alt_samples,
        iso_samples=telemetry.iso_samples,
        exposure_samples=telemetry.exposure_samples,
        temperature_samples=telemetry.temperature_samples,
        font_path="",
        layout=layout,
        field_samples=telemetry.fit_data,
        fit_data=telemetry.fit_data,
        gps_track=telemetry.get_gps_track_for_source("fit"),
        target_fps=60.0,
    )
    print(f"[PARITY] Baseline render ok: {ok}")
    frames = extract_frames_from_video(out_mp4, "before", [5, 15, 25])
    print(f"[PARITY] Extracted baseline frames: {[str(p.name) for p in frames]}")

if __name__ == "__main__":
    main()
