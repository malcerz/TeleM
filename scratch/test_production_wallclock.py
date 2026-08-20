import sys, os, time, json
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

def run_single_export(run_id: int, v_file: Path, fit_file: Path, layout: dict):
    print(f"\n{'='*70}\nURUCHOMIENIE PRODUKCYJNE {run_id}\n{'='*70}")
    
    # 1. PREPARE (telemetry extraction, sync, field mapping)
    t_start = time.perf_counter()
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

    out_file = Path(f"scratch/prod_export_run{run_id}.mp4")
    
    # 2. Production export
    n_frames = stream_overlay_to_ffmpeg(
        ffmpeg_exe="ffmpeg",
        input_files=[str(v_file)],
        output_file=str(out_file),
        duration_s=37.74,
        start_dt_utc=anchor_dt,
        tz_offset_hours=0.0,
        speed_samples=speed_samples,
        track_samples=track_samples,
        alt_samples=alt_samples,
        font_path="",
        layout=layout,
        field_samples=field_samples,
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
    t_end = time.perf_counter()
    wall_total = t_end - t_start
    print(f"[RUN {run_id} COMPLETE] Wall-clock: {wall_total:.3f} s | Real FPS: {n_frames / wall_total:.2f}")

def main():
    v_file = Path('Video/GX020079.mp4')
    fit_file = Path('Video/Morning_Ride.fit')
    
    # Load exact production layout (def_layout.json)
    layout = normalize_layout("def_layout.json", 1920, 1080)

    print("Rozpoczynam 3 pełne powtórzenia produkcyjnego eksportu NVIDIA...")
    for run_id in (1, 2, 3):
        run_single_export(run_id, v_file, fit_file, layout)

if __name__ == "__main__":
    main()
