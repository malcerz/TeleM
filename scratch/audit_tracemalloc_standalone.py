"""Standalone tracemalloc diagnostic for the AMD render loop (AUDIT ONLY).

Runs a short 30-frame 720p full-preset export with tracemalloc active and
prints the top allocation sites plus per-phase allocation deltas.
"""
import json
import os
import sys
import tracemalloc
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.gui.telemetry_manager import TelemetryDataManager
from src.ffmpeg.amd_native_exporter import export_amd_native_d3d11
from src.telemetry_extract import (
    extract_speed_samples, extract_altitude_samples, extract_track_samples,
    extract_iso_samples, extract_exposure_samples, extract_temperature_samples,
    ensure_records_list, extract_gps_track, smooth_speed_samples,
    interpolate_value, get_rotation_from_metadata, get_container_rotation,
    find_metadata_json, load_json_with_fallback, smooth_speed_values,
    extract_accelerometer_samples, extract_gyroscope_samples,
)

root = ROOT
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

os.environ["AMD_TELEMETRY_MODE"] = "PRECOMPUTED"
os.environ["AMD_NATIVE_HUD_MODE"] = "GPU_HUD"
os.environ["AMD_NATIVE_DECODE_MODE"] = "GPU_HUD_D3D11VA"
os.environ["AMD_MAP_PATH"] = "GPU"
os.environ["AMD_CHART_PATH"] = "GPU_SPLIT"
os.environ["AMD_GAUGE_PATH"] = "GPU"
os.environ["AMD_OVERLAY_PROFILE"] = "0"
os.environ["AMD_AUDIT_ALLOCS"] = "1"

out = root / "scratch" / "audit_tm_alloc.mp4"
if out.exists():
    out.unlink()

tracemalloc.start()
snap0 = tracemalloc.take_snapshot()
ok = export_amd_native_d3d11(
    ffmpeg_exe="ffmpeg",
    input_files=[str(video_path)],
    output_file=str(out),
    duration_s=0.5,  # 30 frames @ 60fps
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
current, peak = tracemalloc.get_traced_memory()
snap1 = tracemalloc.take_snapshot()
tracemalloc.stop()

diff = snap1.compare_to(snap0, "lineno")
print(f"export ok={ok}")
print(f"traced current={current/1024:.1f} KiB peak={peak/1024:.1f} KiB")
print("=== TOP NET ALLOCATION SITES (diff over 30-frame export) ===")
for s in diff[:40]:
    fn = str(Path(s.traceback[0].filename))
    # keep only src files + show key ones
    print("  %-58s size=%12d count=%8d" % (fn.split('TeleM')[-1].lstrip('\\/') + ":" + str(s.traceback[0].lineno), s.size_diff, s.count_diff))
