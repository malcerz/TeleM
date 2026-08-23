import os
import sys
import json
import statistics
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.gui.telemetry_manager import TelemetryDataManager
from src.ffmpeg.amd_native_exporter import export_amd_native_d3d11
from src.telemetry_extract import (
    extract_speed_samples, extract_altitude_samples, extract_track_samples,
    extract_iso_samples, extract_exposure_samples, extract_temperature_samples,
    ensure_records_list, extract_gps_track,
    smooth_speed_samples, interpolate_value, get_rotation_from_metadata,
    get_container_rotation, find_metadata_json, load_json_with_fallback,
    smooth_speed_values, extract_accelerometer_samples, extract_gyroscope_samples,
)

root = Path(__file__).resolve().parents[1]
video_path = root / "Video" / "GX010115.MP4"
json_path = root / "Video" / "GX010115.json"
fit_path = root / "Video" / "Jazda_na_rowerze_w_porze_lunchu.fit"
layout_path = root / "presets" / "cycling_dashboard_v10.json"

with open(layout_path, "r", encoding="utf-8") as f:
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

with open(json_path, "r", encoding="utf-8") as f:
    meta = json.load(f)
records = ensure_records_list(meta)
telemetry.load_gpmf_records(records)
telemetry.load_gps_track(records)
telemetry.load_fit(video_path, telemetry.start_dt_utc, manual_path=fit_path)

out_mp4 = root / "scratch" / "benchmark_etap10l_amd.mp4"
if out_mp4.exists():
    out_mp4.unlink()

os.environ["AMD_TELEMETRY_MODE"] = "PRECOMPUTED"
os.environ["AMD_NATIVE_HUD_MODE"] = "GPU_HUD"
os.environ["AMD_NATIVE_DECODE_MODE"] = "GPU_HUD_D3D11VA"
os.environ["AMD_MAP_PATH"] = "GPU"
os.environ["AMD_CHART_PATH"] = "CPU_REFERENCE"
os.environ["AMD_GAUGE_PATH"] = "GPU"
os.environ["AMD_OVERLAY_PROFILE"] = "1"

print("=" * 60)
print("Running ETAP 10L Production Benchmark (120 frames @ 60fps)...")
print("=" * 60)

t_start = time.perf_counter()
result = export_amd_native_d3d11(
    ffmpeg_exe="ffmpeg",
    input_files=[str(video_path)],
    output_file=str(out_mp4),
    duration_s=2.0,
    video_width=1280,
    video_height=720,
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
t_end = time.perf_counter()
wall_elapsed = t_end - t_start

profile_json = out_mp4.with_suffix(".mp4.amd_profile.json")
with open(profile_json, "r", encoding="utf-8") as f:
    prof = json.load(f)

print(f"\nBenchmark completed in {wall_elapsed:.3f} s.")
print(f"Result: {result}")

# Save analyzed data to a structured JSON for reporting
with open(root / "scratch" / "etap10l_analyzed_metrics.json", "w", encoding="utf-8") as f:
    json.dump({
        "wall_elapsed_s": wall_elapsed,
        "export_result": result,
        "profile": prof,
    }, f, indent=2)

print("\nMetrics written to scratch/etap10l_analyzed_metrics.json")
