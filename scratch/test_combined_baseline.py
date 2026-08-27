import os
import sys
import math
import time
import json
import subprocess
import numpy as np
from pathlib import Path
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.ffmpeg.amd_native_exporter import export_amd_native_d3d11
from src.gui.telemetry_manager import TelemetryDataManager

PRESET = Path("presets/cycling_dashboard_v10.json")
VIDEO = Path("Video/GX010115.MP4")
FIT = Path("Video/Jazda_na_rowerze_w_porze_lunchu.fit")

with open(PRESET, "r", encoding="utf-8") as f:
    layout = json.load(f)

telemetry = TelemetryDataManager()
telemetry.load_gpmf_from_exiftool(VIDEO)
telemetry.load_fit(VIDEO, telemetry.start_dt_utc, manual_path=FIT)
gps_track = telemetry.get_gps_track_for_source("fit")
fit_data = telemetry.fit_data

OUT_DIR = Path("scratch/etap1c_test")
OUT_DIR.mkdir(parents=True, exist_ok=True)
FRAMES_DIR = OUT_DIR / "parity_frames"
FRAMES_DIR.mkdir(parents=True, exist_ok=True)

def run_export(mode_name: str, gpu_map_rotate: bool, after_map_gpu: bool, frame_count: int = 300):
    out_mp4 = OUT_DIR / f"{mode_name}_{frame_count}f.mp4"
    if out_mp4.exists():
        try:
            out_mp4.unlink()
        except Exception:
            pass
            
    os.environ["AMD_GPU_MAP_ROTATE"] = "1" if gpu_map_rotate else "0"
    os.environ["AMD_AFTER_MAP_CHART_GPU"] = "1" if after_map_gpu else "0"
    os.environ["AMD_MAP_PATH"] = "GPU"
    os.environ["AMD_MAP_FILTER"] = "BICUBIC"
    os.environ["AMD_NATIVE_HUD_MODE"] = "GPU_HUD"
    os.environ["AMD_PROFILING"] = "1"
    
    print(f"\n=======================================================")
    print(f"RUNNING: {mode_name} ({frame_count} frames 4K)")
    print(f"AMD_GPU_MAP_ROTATE={os.environ['AMD_GPU_MAP_ROTATE']}, AMD_AFTER_MAP_CHART_GPU={os.environ['AMD_AFTER_MAP_CHART_GPU']}")
    print(f"=======================================================")
    
    t0 = time.perf_counter()
    ok = export_amd_native_d3d11(
        ffmpeg_exe="ffmpeg",
        input_files=[str(VIDEO)],
        output_file=str(out_mp4),
        duration_s=frame_count / 59.94005994,
        video_width=3840,
        video_height=2160,
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
        field_samples=fit_data,
        fit_data=fit_data,
        gps_track=gps_track,
        target_fps=59.94005994,
        video_bitrate="40M",
        quality="speed",
    )
    t1 = time.perf_counter()
    wall_time = t1 - t0
    print(f"Export {mode_name} completed: ok={ok}, wall_time={wall_time:.3f}s")
    return ok, out_mp4

def extract_frame(mp4_path: Path, frame_idx: int, out_png: Path):
    cmd = [
        "ffmpeg", "-y", "-i", str(mp4_path),
        "-vf", f"select=eq(n\\,{frame_idx})",
        "-vframes", "1",
        str(out_png)
    ]
    subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)

def calculate_roi_metrics(img1: Image.Image, img2: Image.Image, bbox=None):
    if bbox:
        im1 = img1.crop(bbox)
        im2 = img2.crop(bbox)
    else:
        im1 = img1
        im2 = img2
    a1 = np.array(im1, dtype=np.float32)
    a2 = np.array(im2, dtype=np.float32)
    diff = np.abs(a1 - a2)
    max_d = float(np.max(diff))
    mae = float(np.mean(diff))
    mse = float(np.mean((a1 - a2) ** 2))
    psnr = 100.0 if mse == 0 else 20 * math.log10(255.0 / math.sqrt(mse))
    diff_pixels = int(np.sum(np.any(diff > 0, axis=-1)))
    total_pixels = a1.shape[0] * a1.shape[1]
    return {
        "max_diff": max_d, "mae": mae, "psnr": psnr,
        "diff_pixels": diff_pixels, "total_pixels": total_pixels,
        "diff_pct": diff_pixels / total_pixels * 100.0
    }

if __name__ == "__main__":
    frames_count = 300
    run_export("mode_a_baseline", gpu_map_rotate=False, after_map_gpu=False, frame_count=frames_count)
    run_export("mode_b_gpu_map_only", gpu_map_rotate=True, after_map_gpu=False, frame_count=frames_count)
    run_export("mode_c_combined", gpu_map_rotate=True, after_map_gpu=True, frame_count=frames_count)
