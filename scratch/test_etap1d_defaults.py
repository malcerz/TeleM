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

OUT_DIR = Path("scratch/etap1d_test")
OUT_DIR.mkdir(parents=True, exist_ok=True)

def run_test(case_name: str, env_vars: dict[str, str | None], frame_count: int = 60):
    print(f"\n=========================================================================")
    print(f"RUNNING TEST: {case_name}")
    print(f"ENV OVERRIDES: {env_vars}")
    print(f"=========================================================================")
    
    # Set or clear env vars
    for k, v in env_vars.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v
            
    out_mp4 = OUT_DIR / f"{case_name}_{frame_count}f.mp4"
    if out_mp4.exists():
        try:
            out_mp4.unlink()
        except Exception:
            pass

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
    print(f"Test {case_name} finished: ok={ok}, wall_time={t1-t0:.3f}s")
    assert ok, f"Export failed for {case_name}"
    return ok

if __name__ == "__main__":
    # Test A: Default (no env set)
    run_test("test_a_default", {
        "AMD_GPU_MAP_ROTATE": None,
        "AMD_AFTER_MAP_CHART_GPU": None
    }, frame_count=60)
    
    # Test B: Full fallback (both explicit 0)
    run_test("test_b_full_fallback", {
        "AMD_GPU_MAP_ROTATE": "0",
        "AMD_AFTER_MAP_CHART_GPU": "0"
    }, frame_count=60)
    
    # Test C1: Map OFF, Charts ON
    run_test("test_c1_map_off_charts_on", {
        "AMD_GPU_MAP_ROTATE": "0",
        "AMD_AFTER_MAP_CHART_GPU": "1"
    }, frame_count=60)
    
    # Test C2: Map ON, Charts OFF
    run_test("test_c2_map_on_charts_off", {
        "AMD_GPU_MAP_ROTATE": "1",
        "AMD_AFTER_MAP_CHART_GPU": "0"
    }, frame_count=60)
    
    print("\nALL ETAP 1D CONFIGURATION TESTS PASSED SUCCESSFULLY!")
