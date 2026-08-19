"""Run live export of 90 frames and check timing breakdown."""
import json
import os
import sys
import time
from pathlib import Path

root = Path("c:/_DEV/TeleM")
sys.path.insert(0, str(root))

from src.gui.telemetry_manager import TelemetryDataManager
from src.telemetry_extract import (
    ensure_records_list,
    extract_altitude_samples,
    extract_exposure_samples,
    extract_iso_samples,
    extract_speed_samples,
    extract_temperature_samples,
    extract_track_samples,
    interpolate_value,
    load_json_with_fallback,
    smooth_speed_samples,
)
from src.ffmpeg.streaming import stream_overlay_to_ffmpeg

os.environ["AMD_NATIVE_D3D11"] = "1"
os.environ["AMD_NATIVE_DECODE"] = "D3D11VA"
os.environ["AMD_NATIVE_HUD_MODE"] = "GPU_HUD"
os.environ["AMD_FRAME_ACCOUNTING"] = "1"
os.environ["AMD_OVERLAY_PROFILE"] = "0"
os.environ["AMD_AMF_DIAG"] = "1"
os.environ["AMD_CHART_PATH"] = "GPU_SPLIT"
os.environ["AMD_GAUGE_PATH"] = "GPU"
os.environ["AMD_MAP_PATH"] = "GPU"

records = ensure_records_list(load_json_with_fallback(root / "Video" / "GX030120.json"))
tm = TelemetryDataManager(
    extract_speed_fn=extract_speed_samples,
    extract_altitude_fn=extract_altitude_samples,
    extract_track_fn=extract_track_samples,
    extract_iso_fn=extract_iso_samples,
    extract_exposure_fn=extract_exposure_samples,
    extract_temperature_fn=extract_temperature_samples,
    smooth_fn=smooth_speed_samples,
    interpolate_fn=interpolate_value,
)
tm.load_gpmf_records(records)
tm.load_fit(root / "Video" / "Poranna_jazda_na_rowerze.fit")
tm.start_dt_utc = tm.speed_samples[0][0]

layout = json.load(open(root / "def_layout.json", encoding="utf-8"))
speed = smooth_speed_samples(tm.speed_samples, "moving_average", 5)
alt = smooth_speed_samples(tm.alt_samples, "moving_average", 5)
track = tm.track_samples

out_mp4 = root / "scratch" / "test_live_90f.mp4"
if out_mp4.exists():
    try:
        out_mp4.unlink()
    except Exception:
        pass

duration = 90 * (1001 / 30000)

t0 = time.perf_counter()
res = stream_overlay_to_ffmpeg(
    ffmpeg_exe=r"C:\tools\ffmpeg.exe",
    input_files=[str(root / "Video" / "GX030120.MP4")],
    output_file=str(out_mp4),
    duration_s=duration,
    start_dt_utc=tm.start_dt_utc,
    tz_offset_hours=0.0,
    speed_samples=speed,
    track_samples=track,
    alt_samples=alt,
    field_samples={"speed_samples": speed, "track_samples": track, "alt_samples": alt},
    iso_samples=tm.iso_samples,
    exposure_samples=tm.exposure_samples,
    temperature_samples=tm.temperature_samples,
    fit_data=tm.fit_data,
    gps_track=tm.get_gps_track_for_source("fit"),
    layout=layout,
    font_path="arial.ttf",
    encoder="amd_native",
)
t1 = time.perf_counter()
print(f"Export done in {t1 - t0:.2f}s, res={res}")

prof_json = out_mp4.with_name(out_mp4.name + ".amd_profile.json")
if prof_json.exists():
    pdata = json.load(open(prof_json))
    timings = pdata.get("timings", {})
    for k in ["compose_overlay", "map_cpu_upload", "above_compose", "VideoProcessor CPU submit", "gauge_tobytes", "chart_dynamic_tobytes"]:
        print(f"Timing {k}: {timings.get(k)}")
