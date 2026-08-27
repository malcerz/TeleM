import os
import sys
import time
import json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Add DLL directory for MinGW
os.add_dll_directory(r"C:\tools\mingw64\bin")
os.add_dll_directory(r"c:\_DEV\TeleM\native\d3d11_amf_pipeline\bin")

from src.gui.telemetry_manager import TelemetryDataManager
from src.gui.layout_manager import normalize_layout
from src.ffmpeg.amd_native_exporter import export_amd_native_d3d11

OUT_DIR = Path("scratch/intel_port_test")
OUT_DIR.mkdir(parents=True, exist_ok=True)

PRESET = Path("presets/cycling_dashboard_v10.json")
VIDEO = Path("Video/GX010115.MP4")
FIT = Path("Video/Jazda_na_rowerze_w_porze_lunchu.fit")

def main():
    print("=" * 80)
    print("AMD BENCHMARK FULL 1131 FRAMES (4K / 3840x2160)")
    print("=" * 80)
    
    with open(PRESET, "r", encoding="utf-8") as f:
        layout = json.load(f)
        
    telemetry = TelemetryDataManager()
    telemetry.load_gpmf_from_exiftool(VIDEO)
    telemetry.load_fit(VIDEO, telemetry.start_dt_utc, manual_path=FIT)
    
    out_mp4 = OUT_DIR / "bench_4k_1131f.mp4"
    if out_mp4.exists():
        out_mp4.unlink()
        
    # Keep baseline CPU reference for charts (or standard default)
    os.environ["AMD_AFTER_MAP_CHART_GPU"] = "0"
    os.environ["AMD_AFTER_MAP_CHART_CAPTURE_DIAG"] = "0"
    
    t0 = time.perf_counter()
    ok = export_amd_native_d3d11(
        ffmpeg_exe="ffmpeg",
        input_files=[str(VIDEO)],
        output_file=str(out_mp4),
        duration_s=1131 / 59.94005994, # full clip (1131 frames)
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
        field_samples=telemetry.fit_data,
        fit_data=telemetry.fit_data,
        gps_track=telemetry.get_gps_track_for_source("fit"),
        target_fps=59.94005994,
        video_bitrate="40M",
        quality="speed",
    )
    t1 = time.perf_counter()
    assert ok, f"Export failed for {out_mp4}"
    
    profile_json = Path(str(out_mp4) + ".amd_profile.json")
    if profile_json.exists():
        with open(profile_json, "r", encoding="utf-8") as pf:
            pdata = json.load(pf)
        print("\n" + "=" * 80)
        print("PROFILE SUMMARY FROM JSON:")
        print("=" * 80)
        print(f"Total wall-clock: {pdata.get('total_wall_clock_s'):.3f} s")
        print(f"True FPS: {pdata.get('true_fps'):.3f}")
        timings = pdata.get("timings", {})
        for stage, stats in timings.items():
            if isinstance(stats, dict):
                print(f"{stage:<35} AVG: {stats.get('avg', 0):>8.3f} ms | Median: {stats.get('median', 0):>8.3f} ms | P95: {stats.get('p95', 0):>8.3f} ms")

if __name__ == "__main__":
    main()
