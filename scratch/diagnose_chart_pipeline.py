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
from src.indicators.chart_builder import build_chart_data, clip_chart_data, ChartHistory
from src.indicators.chart import _render_chart_indicator
from src.overlay_renderer import compose_overlay
from src.ffmpeg.worker_cache import init_worker, WORKER_CACHE, _get_source_samples, _resolve_cache_samples
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

# Check what streaming.py was building:
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

# Correct builder helpers:
def _get_src_samples_correct(src: str):
    gpx_spd, gpx_trk, gpx_alt = [], [], []
    fit_spd = fit_data.get("speed", []) if fit_data else []
    fit_trk = fit_data.get("track", []) if fit_data else []
    fit_alt = fit_data.get("alt", []) if fit_data else []
    if src == "gpx":
        return (gpx_spd, gpx_trk, gpx_alt)
    if src == "fit":
        return (fit_spd, fit_trk, fit_alt)
    return (speed_samples, track_samples, alt_samples)

def _resolve_samples_correct(field_name: str, src: str = "fit", indicator_key: str | None = None):
    if src == "fit" and fit_data:
        return fit_data.get(field_name, [])
    return []

correct_chart_data = build_chart_data(
    layout,
    _get_src_samples_correct,
    _resolve_samples_correct,
    start_dt_utc=anchor_dt,
    end_dt_utc=end_dt_utc,
    source_activity_ranges=source_ranges,
)

print("Correct chart data built:")
for k, v in correct_chart_data.items():
    print(f"  {k:25s}: len={len(v)} pts | start={getattr(v, 'chart_start_dt', None)} | end={getattr(v, 'chart_end_dt', None)}")

# Build precompute cache with correct chart_data
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
    chart_data=correct_chart_data,
    total_frames=5400,
    target_fps=29.97,
)

fd_0 = precompute_cache.lookup(0)
fd_2700 = precompute_cache.lookup(2700)
fd_5399 = precompute_cache.lookup(5399)

print("\nPrecompute lookup test:")
print(f"  Frame 0:    chart_data keys = {list(fd_0['chart_data'].keys())}")
print(f"  Frame 2700: chart_data keys = {list(fd_2700['chart_data'].keys())}")
print(f"  Frame 5399: chart_data keys = {list(fd_5399['chart_data'].keys())}")

out_dir = Path("scratch/chart_diagnostics")
out_dir.mkdir(parents=True, exist_ok=True)

img_0 = compose_overlay(1920, 1080, layout, font_path="", **fd_0)
img_2700 = compose_overlay(1920, 1080, layout, font_path="", **fd_2700)
img_5399 = compose_overlay(1920, 1080, layout, font_path="", **fd_5399)

img_0.save(out_dir / "frame_0.png")
img_2700.save(out_dir / "frame_2700.png")
img_5399.save(out_dir / "frame_5399.png")

print("\nSaved diagnostics images to scratch/chart_diagnostics/")
