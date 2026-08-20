import sys, os, time, json
from pathlib import Path
_root = Path(__file__).resolve().parent.parent
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

from datetime import datetime, timedelta
import numpy as np
from PIL import Image

from telemetry_fit import process_fit
from src.gui.layout_manager import normalize_layout
from src.telemetry_extract import (
    load_json_with_fallback, ensure_records_list,
    extract_speed_samples, extract_altitude_samples, extract_track_samples,
    extract_iso_samples, extract_exposure_samples, extract_temperature_samples,
    find_gps_anchor,
)
from src.indicators.chart_builder import build_chart_data, clip_chart_data
from src.indicators.chart import _render_chart_indicator
from src.indicators.frame_data import prepare_overlay_frame_data
from src.overlay_renderer import compose_overlay
from src.ffmpeg.worker_cache import init_worker, WORKER_CACHE, _resolve_cache_value
from src.telemetry_precompute import build_telemetry_cache

json_path = Path("Video/GX030120.json")
fit_path = Path("Video/Poranna_jazda_na_rowerze.fit")

raw_records = ensure_records_list(load_json_with_fallback(json_path))
anchor_dt = find_gps_anchor(raw_records)
fit_data = process_fit(str(fit_path), video_start_dt=anchor_dt)

speed_samples = extract_speed_samples(raw_records)
alt_samples = extract_altitude_samples(raw_records)
track_samples = extract_track_samples(raw_records)
iso_samples = extract_iso_samples(raw_records)
exposure_samples = extract_exposure_samples(raw_records)
temp_samples = extract_temperature_samples(raw_records)

field_samples = {
    "start_dt_utc": anchor_dt,
    "speed_samples": speed_samples,
    "track_samples": track_samples,
    "alt_samples": alt_samples,
    "iso_samples": iso_samples,
    "exposure_samples": exposure_samples,
    "temp_samples": temp_samples,
}

layout = normalize_layout("def_layout.json", 1920, 1080)

# Proper helper for streaming
def _get_src_samples(src: str):
    if src == "gpx":
        return ([], [], [])
    if src == "fit":
        return ((fit_data or {}).get("speed", []), (fit_data or {}).get("track", []), (fit_data or {}).get("alt", []))
    return (speed_samples, track_samples, alt_samples)

def _resolve_samples(field_name: str, source: str = "fit", indicator_key: str | None = None) -> list:
    if source == "fit":
        fit_d = fit_data or {}
        aliases = {
            "power": ("power", "curVpower"), "hr": ("hr", "heart_rate"),
            "cad": ("cad", "cadence"), "atemp": ("atemp", "temperature"),
            "battery": ("battery", "battery_soc"),
        }.get(field_name, (field_name,))
        for name in aliases:
            if fit_d.get(name):
                return list(fit_d[name])
        return []
    if source == "gpmf":
        gpmf_map = {
            "speed": speed_samples, "alt": alt_samples, "altitude": alt_samples,
            "dist": track_samples, "track": track_samples, "iso": iso_samples,
            "exposure": exposure_samples, "temperature": temp_samples,
        }
        return list(gpmf_map.get(field_name, []) or [])
    return []

duration_s = 5400 / 29.97
end_dt_utc = anchor_dt + timedelta(seconds=duration_s)
source_ranges = {}
if fit_data:
    all_fit_pts = [s for s in fit_data.values() if s]
    if all_fit_pts:
        source_ranges["fit"] = (
            min(s[0][0] for s in all_fit_pts),
            max(s[-1][0] for s in all_fit_pts),
        )

# Initialize worker cache
init_worker(
    video_width=1920, video_height=1080,
    field_samples=field_samples,
    layout=layout,
    font_path="",
    fit_data=fit_data,
    start_dt_utc=anchor_dt,
    target_fps=29.97,
    total_overlay_frames=5400,
    gps_track=fit_data.get("track"),
)

chart_data = build_chart_data(
    layout,
    _get_src_samples,
    _resolve_samples,
    start_dt_utc=anchor_dt,
    end_dt_utc=end_dt_utc,
    source_activity_ranges=source_ranges,
)

print(f"Chart data keys: {list(chart_data.keys())}")
for k, v in chart_data.items():
    print(f"  {k}: {len(v)} pts | scope={getattr(v, 'time_scope', None)} | start={getattr(v, 'chart_start_dt', None)} | end={getattr(v, 'chart_end_dt', None)}")

precompute_cache = build_telemetry_cache(
    layout=layout,
    base_dt=anchor_dt,
    tz_offset_hours=0.0,
    start_dt_utc=anchor_dt,
    speed_samples=speed_samples,
    track_samples=track_samples,
    alt_samples=alt_samples,
    iso_samples=iso_samples,
    exposure_samples=exposure_samples,
    temperature_samples=temp_samples,
    fit_data=fit_data,
    gps_track=fit_data.get("track"),
    chart_data=chart_data,
    total_frames=5400,
    target_fps=29.97,
)

# Test 5 check points (0%, 25%, 50%, 75%, 100%)
pts = [0, 1350, 2700, 4050, 5399]
out_dir = Path("scratch/test_fixed_charts")
out_dir.mkdir(parents=True, exist_ok=True)

for p in pts:
    target_dt = anchor_dt + timedelta(seconds=p / 29.97)
    
    # 1. PRECOMPUTE OFF (Live)
    fd_off = prepare_overlay_frame_data(
        layout=layout,
        target_dt=target_dt,
        tz_offset_hours=0.0,
        start_dt_utc=anchor_dt,
        speed_samples=speed_samples,
        track_samples=track_samples,
        alt_samples=alt_samples,
        iso_samples=iso_samples,
        exposure_samples=exposure_samples,
        temperature_samples=temp_samples,
        fit_data=fit_data,
        gps_track=fit_data.get("track"),
        total_frames=5400,
        current_index=p,
        chart_data=chart_data,
        resolve_cache_value=_resolve_cache_value,
        _range_cache=WORKER_CACHE.get("_prep_cache"),
    )
    
    # 2. PRECOMPUTE ON
    fd_on = precompute_cache.lookup(p)

    img_off = compose_overlay(1920, 1080, layout, font_path="", **fd_off)
    img_on = compose_overlay(1920, 1080, layout, font_path="", **fd_on)

    # Pixel diff between OFF and ON
    arr_off = np.array(img_off)
    arr_on = np.array(img_on)
    diff = np.abs(arr_off.astype(np.int32) - arr_on.astype(np.int32))
    max_d = np.max(diff)
    diff_px = np.count_nonzero(diff)
    print(f"Point {p:4d} ({(p/5399)*100:5.1f}%): max_diff={max_d}, diff_pixels={diff_px}")

    img_on.save(out_dir / f"frame_{p}.png")

print("All tests completed successfully!")
