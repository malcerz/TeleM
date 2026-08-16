"""ETAP 5Q — microbench: time_block paste / _clean_transparency cost breakdown.

Decides whether caching ``_clean_transparency`` (numpy scan) is a worthwhile
2nd compose optimization.
"""
import json
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import numpy as np

from src.ffmpeg.worker_cache import WORKER_CACHE, init_worker, _resolve_cache_value
from src.gui.layout_manager import resolve_font_path
from src.gui.telemetry_manager import TelemetryDataManager
from src.indicators.compositor import compose_overlay
from src.indicators.frame_data import (
    build_active_fit_field_plan, prepare_overlay_frame_data,
)
from src.telemetry_extract import (
    ensure_records_list, extract_altitude_samples, extract_exposure_samples,
    extract_iso_samples, extract_speed_samples, extract_temperature_samples,
    extract_track_samples, interpolate_value, load_json_with_fallback,
    smooth_speed_samples,
)

TARGET_FPS = 30000 / 1001
W, H = 3840, 2160

records = ensure_records_list(load_json_with_fallback(ROOT / "Video" / "GX020079.json"))
tm = TelemetryDataManager(
    extract_speed_fn=extract_speed_samples, extract_altitude_fn=extract_altitude_samples,
    extract_track_fn=extract_track_samples, extract_iso_fn=extract_iso_samples,
    extract_exposure_fn=extract_exposure_samples,
    extract_temperature_fn=extract_temperature_samples,
    smooth_fn=smooth_speed_samples, interpolate_fn=interpolate_value,
)
tm.load_gpmf_records(records)
tm.load_fit(ROOT / "Video" / "Morning_Ride.fit")
tm.start_dt_utc = datetime(2026, 8, 5, 4, 28, 11)
layout = json.loads((ROOT / "def_layout.json").read_text(encoding="utf-8"))
speed = smooth_speed_samples(tm.speed_samples, "moving_average", 5)
altitude = smooth_speed_samples(tm.alt_samples, "moving_average", 5)
track = tm.track_samples
gps_track = tm.get_gps_track_for_source(
    layout.get("indicators", {}).get("track_map", {}).get("source", "fit")
)
init_worker(
    video_width=W, video_height=H, font_path=resolve_font_path("Arial"),
    layout=layout, field_samples={"speed_samples": speed, "track_samples": track,
                                   "alt_samples": altitude},
    max_distance_m=track[-1][1] if track else 0,
    iso_samples=tm.iso_samples, exposure_samples=tm.exposure_samples,
    temperature_samples=tm.temperature_samples,
    gpx_speed_samples=tm.gpx_speed_samples, gpx_track_samples=tm.gpx_track_samples,
    gpx_alt_samples=tm.gpx_alt_samples, gpx_power_samples=tm.gpx_power_samples,
    gpx_atemp_samples=tm.gpx_atemp_samples, gpx_hr_samples=tm.gpx_hr_samples,
    gpx_cad_samples=tm.gpx_cad_samples, fit_data=tm.fit_data, gps_track=gps_track,
    start_dt_utc=tm.start_dt_utc, tz_offset_hours=2,
    speed_samples=speed, track_samples=track, alt_samples=altitude,
    target_fps=TARGET_FPS, update_rate_step=1, total_overlay_frames=1131,
)
plan = build_active_fit_field_plan(layout, (tm.fit_data or {}).keys())
base_dt = tm.start_dt_utc


def fd(i):
    curr_dt = base_dt + timedelta(seconds=i / TARGET_FPS)
    return prepare_overlay_frame_data(
        layout=layout, target_dt=curr_dt, start_dt_utc=base_dt, tz_offset_hours=2,
        speed_samples=speed, track_samples=track, alt_samples=altitude,
        iso_samples=tm.iso_samples, exposure_samples=tm.exposure_samples,
        temperature_samples=tm.temperature_samples, total_frames=1131,
        current_index=i, chart_data=WORKER_CACHE.get("_precomputed_chart_data", {}),
        resolve_cache_value=_resolve_cache_value,
        gpx_speed_samples=tm.gpx_speed_samples, gpx_track_samples=tm.gpx_track_samples,
        gpx_alt_samples=tm.gpx_alt_samples, gpx_power_samples=tm.gpx_power_samples,
        gpx_atemp_samples=tm.gpx_atemp_samples, gpx_hr_samples=tm.gpx_hr_samples,
        gpx_cad_samples=tm.gpx_cad_samples, fit_data=tm.fit_data, gps_track=gps_track,
        _range_cache=WORKER_CACHE.get("_prep_cache"), fit_field_plan=plan,
        resolve_stats={"calls": 0, "per_field": {}},
    )


from src.indicators.time_block import render_time_block
from src.indicators.rotated_paste import _clean_transparency
from PIL import Image
import src.indicators.compositor as comp_mod

font_path = resolve_font_path("Arial")
comp_mod.get_overlay_profiler  # ensure import
from src.indicators.profiling import get_overlay_profiler
prof = get_overlay_profiler()

# Render frame 100 a few times to warm caches
kw = fd(100)
for _ in range(3):
    b = {}
    compose_overlay(canvas_w=W, canvas_h=H, layout=layout, font_path=font_path, _bboxes=b, **kw)

# Now get the time_block overlay directly
tb, tbx, tby = render_time_block(W, H, layout, font_path, kw["date_text"], kw["time_text"])
print(f"time_block overlay size: {tb.size}, bbox content: {tb.getbbox()}")

# Measure _clean_transparency cost
arr = np.asarray(tb, dtype=np.uint8)
N = 200
t0 = time.perf_counter()
for _ in range(N):
    _clean_transparency(tb)
dt = (time.perf_counter() - t0) / N * 1000
print(f"_clean_transparency: {dt:.4f} ms/op")

# Measure alpha_composite of time_block content region over transparent canvas
content = tb.crop(tb.getbbox())
t0 = time.perf_counter()
for _ in range(N):
    base = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    base.alpha_composite(content, (tbx, tby))
dt2 = (time.perf_counter() - t0) / N * 1000
print(f"full-canvas alpha_composite of tb: {dt2:.4f} ms/op")

# Measure plain paste
t0 = time.perf_counter()
for _ in range(N):
    base = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    base.paste(tb, (tbx, tby))
dt3 = (time.perf_counter() - t0) / N * 1000
print(f"full-canvas plain paste of tb: {dt3:.4f} ms/op")

# Measure the actual rotated_paste composite over a real HUD canvas (with prior bboxes from a real frame)
b = {}
compose_overlay(canvas_w=W, canvas_h=H, layout=layout, font_path=font_path, _bboxes=b, **kw)
# time_block paste with the real canvas img
img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
from src.indicators.rotated_paste import rotated_paste
cx = tbx + tb.width // 2
cy = tby + tb.height // 2
t0 = time.perf_counter()
for _ in range(N):
    img2 = img.copy()
    rotated_paste(img2, tb, cx, cy, 0, prior_bboxes=list(b.values()), cache_key="time_block")
dt4 = (time.perf_counter() - t0) / N * 1000
print(f"rotated_paste(time_block) over HUD-sized canvas: {dt4:.4f} ms/op")
