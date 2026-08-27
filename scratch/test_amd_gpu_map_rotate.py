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

out_dir = Path("scratch/map_rotate_test")
out_dir.mkdir(parents=True, exist_ok=True)

def run_test(gpu_rotate: bool, frame_count: int = 120):
    mode_str = "rotate_gpu" if gpu_rotate else "rotate_cpu"
    out_mp4 = out_dir / f"test_{mode_str}_{frame_count}f.mp4"
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
    print(f"RUNNING: {mode_str} ({frame_count} frames)")
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
    print(f"Export {mode_str} completed: ok={ok}, wall_time={wall_time:.3f}s")
    return ok, out_mp4

if __name__ == "__main__":
    run_test(gpu_rotate=False, frame_count=120)
    run_test(gpu_rotate=True, frame_count=120)
