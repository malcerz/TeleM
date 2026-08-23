import os
import sys
import json
import time
from pathlib import Path
from collections import defaultdict

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import src.indicators.compositor as compositor
import src.indicators.dispatcher as dispatcher
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

# Detailed per-widget and per-frame records
frame_records = []
current_frame_data = {}

# Instrument compositor.compose_overlay
orig_compose_overlay = compositor.compose_overlay
orig_render_value_indicator = compositor.render_value_indicator
orig_render_time_display = compositor.render_time_display
orig_rotated_paste = compositor.rotated_paste

def hooked_compose_overlay(*args, **kwargs):
    reuse_canvas = kwargs.get("reuse_canvas") or (args[20] if len(args) > 20 else None)
    scope_name = "below" if reuse_canvas == "below" else "above"
    
    t0 = time.perf_counter()
    res = orig_compose_overlay(*args, **kwargs)
    t1 = time.perf_counter()
    
    elapsed = (t1 - t0) * 1000.0
    current_frame_data[f"{scope_name}_compose_ms"] = elapsed
    
    if scope_name == "above":
        # Frame composition complete for this frame
        frame_records.append(dict(current_frame_data))
        current_frame_data.clear()
        
    return res

def hooked_render_time_display(*args, **kwargs):
    t0 = time.perf_counter()
    res = orig_render_time_display(*args, **kwargs)
    t1 = time.perf_counter()
    current_frame_data["widget.time_display.render_ms"] = (t1 - t0) * 1000.0
    return res

def hooked_render_value_indicator(*args, **kwargs):
    key = args[4] if len(args) > 4 else kwargs.get("key")
    t0 = time.perf_counter()
    res = orig_render_value_indicator(*args, **kwargs)
    t1 = time.perf_counter()
    current_frame_data[f"widget.{key}.render_ms"] = (t1 - t0) * 1000.0
    return res

def hooked_rotated_paste(target, source, cx, cy, rotation, *args, **kwargs):
    cache_key = kwargs.get("cache_key", "unknown")
    t0 = time.perf_counter()
    res = orig_rotated_paste(target, source, cx, cy, rotation, *args, **kwargs)
    t1 = time.perf_counter()
    current_frame_data[f"widget.{cache_key}.paste_ms"] = (t1 - t0) * 1000.0
    return res

import src.ffmpeg.amd_native_exporter as amd_native_exporter

orig_exporter_compose = amd_native_exporter.compose_overlay
amd_native_exporter.compose_overlay = hooked_compose_overlay
compositor.compose_overlay = hooked_compose_overlay
compositor.render_time_display = hooked_render_time_display
compositor.render_value_indicator = hooked_render_value_indicator
compositor.rotated_paste = hooked_rotated_paste

out_mp4 = root / "scratch" / "benchmark_etap10l_detailed.mp4"
if out_mp4.exists():
    out_mp4.unlink()

os.environ["AMD_TELEMETRY_MODE"] = "PRECOMPUTED"
os.environ["AMD_NATIVE_HUD_MODE"] = "GPU_HUD"
os.environ["AMD_NATIVE_DECODE_MODE"] = "GPU_HUD_D3D11VA"
os.environ["AMD_MAP_PATH"] = "GPU"
os.environ["AMD_CHART_PATH"] = "CPU_REFERENCE"
os.environ["AMD_GAUGE_PATH"] = "GPU"
os.environ["AMD_OVERLAY_PROFILE"] = "1"

print("=" * 70)
print("Starting Detailed ETAP 10L Profile (120 frames @ 60 FPS)...")
print("=" * 70)

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

# Restore original functions
compositor.compose_overlay = orig_compose_overlay
compositor.render_time_display = orig_render_time_display
compositor.render_value_indicator = orig_render_value_indicator
compositor.rotated_paste = orig_rotated_paste

profile_json = out_mp4.with_suffix(".mp4.amd_profile.json")
with open(profile_json, "r", encoding="utf-8") as f:
    prof = json.load(f)

print(f"\nDetailed run finished in {wall_elapsed:.3f} s. Recorded {len(frame_records)} frame measurements.")

# Save combined detailed profile
detailed_metrics_path = root / "scratch" / "etap10l_detailed_measurements.json"
with open(detailed_metrics_path, "w", encoding="utf-8") as f:
    json.dump({
        "wall_elapsed_s": wall_elapsed,
        "export_result": result,
        "exporter_profile": prof,
        "frame_records": frame_records,
    }, f, indent=2)

print(f"Detailed measurements saved to {detailed_metrics_path}")
