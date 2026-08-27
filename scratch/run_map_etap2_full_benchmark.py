import os
import sys
import time
import json
from pathlib import Path

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

OUT_DIR = Path("scratch/map_rotate_test")
OUT_DIR.mkdir(parents=True, exist_ok=True)

def run_benchmark(gpu_rotate: bool, total_frames: int = 1131):
    mode_name = "GPU_MAP_ROTATE_ON" if gpu_rotate else "GPU_MAP_ROTATE_OFF_BASELINE"
    out_mp4 = OUT_DIR / f"benchmark_4k_{mode_name}_{total_frames}f.mp4"
    if out_mp4.exists():
        try:
            out_mp4.unlink()
        except Exception:
            pass
            
    os.environ["AMD_GPU_MAP_ROTATE"] = "1" if gpu_rotate else "0"
    os.environ["AMD_MAP_PATH"] = "GPU"
    os.environ["AMD_MAP_FILTER"] = "BICUBIC"
    os.environ["AMD_NATIVE_HUD_MODE"] = "GPU_HUD"
    os.environ["AMD_PROFILING"] = "1"
    
    print(f"\n=======================================================")
    print(f"BENCHMARK: {mode_name} ({total_frames} frames 4K)")
    print(f"=======================================================")
    
    t0 = time.perf_counter()
    ok = export_amd_native_d3d11(
        ffmpeg_exe="ffmpeg",
        input_files=[str(VIDEO)],
        output_file=str(out_mp4),
        duration_s=total_frames / 59.94005994,
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
    print(f"Benchmark {mode_name} result: ok={ok}, total_wall_time={wall_time:.3f}s")
    return ok, out_mp4

if __name__ == "__main__":
    frames = 1131
    if len(sys.argv) > 1:
        frames = int(sys.argv[1])
    
    run_benchmark(gpu_rotate=False, total_frames=frames)
    run_benchmark(gpu_rotate=True, total_frames=frames)
