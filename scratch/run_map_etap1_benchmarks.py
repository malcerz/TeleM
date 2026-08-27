import os
import sys
import time
import json
import shutil
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Add DLL directory for MinGW
os.add_dll_directory(r"C:\tools\mingw64\bin")
os.add_dll_directory(r"c:\_DEV\TeleM\native\d3d11_amf_pipeline\bin")

from src.gui.telemetry_manager import TelemetryDataManager
from src.indicators.moving_map import ensure_map_tiles_cached
from src.moving_map import (
    TileCache,
    set_map_network_allowed,
    reset_map_tile_stats,
    get_map_tile_stats,
)
from src.ffmpeg.amd_native_exporter import export_amd_native_d3d11

OUT_DIR = Path("scratch/map_etap1_test")
OUT_DIR.mkdir(parents=True, exist_ok=True)

PRESET = Path("presets/cycling_dashboard_v10.json")
VIDEO = Path("Video/GX010115.MP4")
FIT = Path("Video/Jazda_na_rowerze_w_porze_lunchu.fit")

def run_single_benchmark(label: str, cache_dir: Path | None = None) -> dict:
    print("\n" + "=" * 80)
    print(f"RUNNING BENCHMARK: {label} (1131 FRAMES 4K)")
    print("=" * 80)

    with open(PRESET, "r", encoding="utf-8") as f:
        layout = json.load(f)

    telemetry = TelemetryDataManager()
    telemetry.load_gpmf_from_exiftool(VIDEO)
    telemetry.load_fit(VIDEO, telemetry.start_dt_utc, manual_path=FIT)
    gps_track = telemetry.get_gps_track_for_source("fit")

    out_mp4 = OUT_DIR / f"bench_{label.lower().replace(' ', '_')}.mp4"
    if out_mp4.exists():
        out_mp4.unlink()

    os.environ["AMD_AFTER_MAP_CHART_GPU"] = "0"
    os.environ["AMD_AFTER_MAP_CHART_CAPTURE_DIAG"] = "0"

    t0 = time.perf_counter()
    ok = export_amd_native_d3d11(
        ffmpeg_exe="ffmpeg",
        input_files=[str(VIDEO)],
        output_file=str(out_mp4),
        duration_s=1131 / 59.94005994,
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
        gps_track=gps_track,
        target_fps=59.94005994,
        video_bitrate="40M",
        quality="speed",
    )
    t1 = time.perf_counter()
    assert ok, f"Export failed for {out_mp4}"

    prof_json = Path(str(out_mp4) + ".amd_profile.json")
    prof_data = {}
    if prof_json.exists():
        with open(prof_json, "r", encoding="utf-8") as pf:
            prof_data = json.load(pf)

    stats = get_map_tile_stats()
    result = {
        "label": label,
        "total_wall_s": t1 - t0,
        "tile_stats": stats,
        "profile": prof_data,
    }
    print(f"\n[{label} RESULT]")
    print(f"Total Wall: {t1 - t0:.3f} s")
    print(f"Tile stats during frame loop: {stats}")
    if prof_data:
        print(f"RENDER FPS: {prof_data.get('metrics', {}).get('render_fps')}")
        print(f"USER EFFECTIVE FPS: {prof_data.get('metrics', {}).get('user_effective_fps')}")
        print(f"map_cpu_upload AVG ms: {prof_data.get('timings', {}).get('map_cpu_upload', {}).get('avg')}")
    return result

def main():
    results = {}

    # 1. COLD CACHE TEST
    # Clear cache or test with preload from scratch
    print("Preparing COLD CACHE test...")
    # Run cold test
    results["COLD"] = run_single_benchmark("COLD_START_PLUS_PRELOAD")

    # 2. WARM CACHE TEST
    print("Preparing WARM CACHE test...")
    results["WARM"] = run_single_benchmark("WARM_CACHE")

    summary_file = OUT_DIR / "map_etap1_summary.json"
    with open(summary_file, "w", encoding="utf-8") as sf:
        json.dump(results, sf, indent=2)
    print(f"\nSummary written to {summary_file}")

if __name__ == "__main__":
    main()
