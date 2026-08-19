import json
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

root = Path("c:/_DEV/TeleM")
sys.path.insert(0, str(root))

from src.indicators.compositor import compose_overlay
from src.indicators.helpers import _STATIC_CACHE
from src.indicators.chart import _FINAL_STATIC_CHART_CACHE
from src.indicators.chart_utils import _CHART_BG_CACHE
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
from src.telemetry_precompute import build_telemetry_cache

root = Path("c:/_DEV/TeleM")

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
start_dt = tm.speed_samples[0][0]

layout = json.load(open(root / "def_layout.json", encoding="utf-8"))
font_path = "arial.ttf"

cache = build_telemetry_cache(
    layout=layout,
    base_dt=start_dt,
    tz_offset_hours=0.0,
    start_dt_utc=start_dt,
    speed_samples=smooth_speed_samples(tm.speed_samples, "moving_average", 5),
    track_samples=tm.track_samples,
    alt_samples=smooth_speed_samples(tm.alt_samples, "moving_average", 5),
    iso_samples=tm.iso_samples,
    exposure_samples=tm.exposure_samples,
    temperature_samples=tm.temperature_samples,
    fit_data=tm.fit_data,
    gps_track=tm.get_gps_track_for_source("fit"),
    total_frames=900,
    target_fps=29.97,
)

print(f"Precomputed {cache.frames} frames.")

# Let's inspect cache entries before and after frame 0, 1, 2, ...
print(f"Initial cache sizes: _FINAL_STATIC_CHART_CACHE={len(_FINAL_STATIC_CHART_CACHE)}, _CHART_BG_CACHE={len(_CHART_BG_CACHE)}")

gpu_chart_keys = {"fit_cadence_text", "fit_heart_rate_text"}
gpu_capture = {}

for f in [0, 1, 2, 10, 50, 100]:
    _FINAL_STATIC_CHART_CACHE.clear()
    _CHART_BG_CACHE.clear()
    fk = cache.lookup(f)
    t0 = time.perf_counter()
    img = compose_overlay(
        canvas_w=3840,
        canvas_h=2160,
        layout=layout,
        font_path=font_path,
        gpu_capture_keys=gpu_chart_keys,
        gpu_capture=gpu_capture,
        split_chart_keys=gpu_chart_keys,
        **fk,
    )
    t1 = time.perf_counter()
    print(f"Frame {f:3d} (cold caches): compose_overlay wall = {(t1 - t0)*1000.0:.3f} ms | _FINAL_STATIC_CHART_CACHE={len(_FINAL_STATIC_CHART_CACHE)}, _CHART_BG_CACHE={len(_CHART_BG_CACHE)}")

# Now test warm cache (consecutive frames)
print("\n--- WARM CACHE CONSECUTIVE FRAMES ---")
times = []
for f in range(100):
    fk = cache.lookup(f)
    t0 = time.perf_counter()
    img = compose_overlay(
        canvas_w=3840,
        canvas_h=2160,
        layout=layout,
        font_path=font_path,
        gpu_capture_keys=gpu_chart_keys,
        gpu_capture=gpu_capture,
        split_chart_keys=gpu_chart_keys,
        **fk,
    )
    t1 = time.perf_counter()
    times.append((t1 - t0) * 1000.0)

import numpy as np
print(f"Frames 0..99 warm: median={np.median(times):.3f} ms, p95={np.percentile(times, 95):.3f} ms, mean={np.mean(times):.3f} ms, min={np.min(times):.3f} ms, max={np.max(times):.3f} ms")
print(f"End cache sizes: _FINAL_STATIC_CHART_CACHE={len(_FINAL_STATIC_CHART_CACHE)}, _CHART_BG_CACHE={len(_CHART_BG_CACHE)}")
