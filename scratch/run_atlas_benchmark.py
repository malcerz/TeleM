import sys, os, time, subprocess, json
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
from scratch.gpu_monitor import GPUMonitor

v_file = Path('Video/GX020079.mp4')
fit_file = Path('Video/Morning_Ride.fit')
n_frames = 1132

def main():
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

    # Atlas Layout (Time block at top + Bottom indicators -> 1112x668 Atlas)
    atlas_layout = normalize_layout("def_layout.json", 1920, 1080)
    for k, v in list(atlas_layout["indicators"].items()):
        if k not in ("time_block", "fit_cadence_text", "fit_enhanced_speed_text", "fit_heart_rate_text"):
            v["enabled"] = False

    def run_single_atlas():
        mon = GPUMonitor(interval=0.05)
        mon.start()
        t0 = time.perf_counter()
        out_f = Path("scratch/etap4c_telem_atlas_out.mp4")
        stream_overlay_to_ffmpeg(
            ffmpeg_exe="ffmpeg", input_files=[str(v_file)], output_file=str(out_f),
            duration_s=37.74, start_dt_utc=anchor_dt, tz_offset_hours=0.0,
            speed_samples=speed_samples, track_samples=track_samples, alt_samples=alt_samples,
            font_path="", layout=atlas_layout, field_samples=field_samples, target_fps=29.97,
            update_rate_step=1, workers=4, encoder="nv", gpu=0, video_bitrate="40M",
            render_w=3840, render_h=2160, resolution_name="source", rotation_degrees=0,
            container_rotation=0, overlay_w=1920, overlay_h=1080,
            iso_samples=iso_samples, exposure_samples=exposure_samples, temperature_samples=temp_samples,
            fit_data=fit_data, gps_track=fit_data.get("track"),
        )
        t1 = time.perf_counter()
        mon.stop()
        elapsed = t1 - t0
        fps = n_frames / elapsed
        stats = mon.get_stats()
        return elapsed, fps, stats

    print("Running 3x MULTI-REGION ATLAS TeleM benchmark...")
    elapsed_list = []
    fps_list = []
    stats_list = []

    for i in range(1, 4):
        el, fps, st = run_single_atlas()
        elapsed_list.append(el)
        fps_list.append(fps)
        stats_list.append(st)
        print(f"Run {i}: {el:.3f} s | {fps:.1f} FPS | NVDEC: {st.get('nvdec_avg',0):.1f}% | NVENC: {st.get('nvenc_avg',0):.1f}% | CUDA: {st.get('gpu_avg',0):.1f}% | CPU: {st.get('cpu_avg',0):.1f}%")

    with open("scratch/etap4c_benchmark_results.json", "r", encoding="utf-8") as f:
        res = json.load(f)

    med_idx = int(np.argsort(fps_list)[1])
    res["TEST_D_ATLAS"] = {
        "name": "TEST D (MULTI-REGION ATLAS TeleM STAGE 4B)",
        "runs_elapsed": elapsed_list,
        "runs_fps": fps_list,
        "min_fps": float(np.min(fps_list)),
        "max_fps": float(np.max(fps_list)),
        "median_fps": float(np.median(fps_list)),
        "median_elapsed": float(np.median(elapsed_list)),
        "median_stats": stats_list[med_idx],
    }

    with open("scratch/etap4c_benchmark_results.json", "w", encoding="utf-8") as f:
        json.dump(res, f, indent=2)

    print("\nUpdated results saved with TEST_D_ATLAS!")

if __name__ == "__main__":
    main()
