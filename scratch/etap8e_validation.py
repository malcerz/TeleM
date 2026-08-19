"""ETAP 8E Real Material & Pipeline Validation Script."""
from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from PIL import Image

root = Path("c:/_DEV/TeleM")
sys.path.insert(0, str(root))

from src.gui.layout_manager import resolve_font_path
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
from src.indicators.chart_builder import build_chart_data, ChartHistory
from src.indicators.compositor import compose_overlay
from src.indicators.frame_data import prepare_overlay_frame_data
from src.telemetry_precompute import build_telemetry_cache
from src.ffmpeg.worker_cache import init_worker, WORKER_CACHE

out_dir = root / "Raporty" / "AMD_ETAP8E"
out_dir.mkdir(parents=True, exist_ok=True)

# 1. Load Data
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

# Video parameters
video_start_dt = tm.speed_samples[0][0]  # 2026-08-18 04:46:25.700000+00:00
tm.start_dt_utc = video_start_dt.replace(tzinfo=None)
full_duration_s = 5395 * (1001 / 30000)  # 180.013s
video_end_dt = video_start_dt + timedelta(seconds=full_duration_s)
fps = 30000 / 1001

with (root / "def_layout.json").open(encoding="utf-8") as fh:
    layout = json.load(fh)

# Enable CAD and HR as charts
layout["indicators"]["fit_cadence_text"]["enabled"] = True
layout["indicators"]["fit_cadence_text"]["form"] = "chart"
layout["indicators"]["fit_heart_rate_text"]["enabled"] = True
layout["indicators"]["fit_heart_rate_text"]["form"] = "chart"

font_path = resolve_font_path("Arial")

# Build full video-visible chart data
chart_data = build_chart_data(
    layout,
    tm.get_samples_for_source,
    lambda field, src, key=None: tm.resolve_samples(field, src, indicator_key=key),
    start_dt_utc=video_start_dt,
    end_dt_utc=video_end_dt,
)

print(f"=== CHART DATA INITIALIZATION ===")
for k, v in chart_data.items():
    print(f"Chart key: {k}, count: {len(v)}, start: {v.timestamps[0]}, end: {v.timestamps[-1]}")

test_timestamps = [0.0, 14.3, 60.0, 120.0, 175.0, 179.9]
results = []

# Build PRECOMPUTED cache
telemetry_cache = build_telemetry_cache(
    layout=layout,
    base_dt=video_start_dt,
    tz_offset_hours=0.0,
    start_dt_utc=video_start_dt,
    speed_samples=tm.speed_samples,
    track_samples=tm.track_samples,
    alt_samples=tm.alt_samples,
    iso_samples=tm.iso_samples,
    exposure_samples=tm.exposure_samples,
    temperature_samples=tm.temperature_samples,
    fit_data=tm.fit_data,
    gps_track=tm.get_gps_track_for_source("fit"),
    chart_data=chart_data,
    resolve_cache_value=lambda field, src, dt, key=None: tm.resolve_value(field, dt, source=src),
    total_frames=5395,
    target_fps=fps,
)

# Init WORKER_CACHE
init_worker(
    video_width=3840,
    video_height=2160,
    font_path=font_path,
    layout=layout,
    field_samples={"speed_samples": tm.speed_samples, "track_samples": tm.track_samples, "alt_samples": tm.alt_samples},
    max_distance_m=tm.track_samples[-1][1] if tm.track_samples else 1000.0,
    iso_samples=tm.iso_samples,
    exposure_samples=tm.exposure_samples,
    temperature_samples=tm.temperature_samples,
    fit_data=tm.fit_data,
    gps_track=tm.get_gps_track_for_source("fit"),
    start_dt_utc=video_start_dt,
    tz_offset_hours=0.0,
    speed_samples=tm.speed_samples,
    track_samples=tm.track_samples,
    alt_samples=tm.alt_samples,
    target_fps=fps,
    total_overlay_frames=5395,
)

print("\n=== TIMELINE & PARITY VALIDATION TABLE ===")
for sec in test_timestamps:
    target_dt = video_start_dt + timedelta(seconds=sec)
    frame_idx = int(round(sec * fps))
    frame_idx = min(5394, frame_idx)

    # 1. Preview / live frame_data
    live_frame = prepare_overlay_frame_data(
        layout=layout,
        target_dt=target_dt,
        tz_offset_hours=0.0,
        start_dt_utc=video_start_dt,
        speed_samples=tm.speed_samples,
        track_samples=tm.track_samples,
        alt_samples=tm.alt_samples,
        iso_samples=tm.iso_samples,
        exposure_samples=tm.exposure_samples,
        temperature_samples=tm.temperature_samples,
        fit_data=tm.fit_data,
        gps_track=tm.get_gps_track_for_source("fit"),
        total_frames=5395,
        current_index=frame_idx,
        chart_data=chart_data,
        resolve_cache_value=lambda field, src, dt, key=None: tm.resolve_value(field, dt, source=src),
    )

    # 2. PRECOMPUTED lookup
    cached_frame = telemetry_cache.lookup(frame_idx)

    # 3. Worker cache chart data
    worker_chart = WORKER_CACHE["_precomputed_chart_data"]

    hr_live = live_frame["chart_data"]["fit_heart_rate_text"]
    cad_live = live_frame["chart_data"]["fit_cadence_text"]
    hr_cached = cached_frame["chart_data"]["fit_heart_rate_text"]
    cad_cached = cached_frame["chart_data"]["fit_cadence_text"]
    hr_worker = worker_chart["fit_heart_rate_text"]

    # Invariants
    assert len(hr_live) == len(hr_cached) == len(hr_worker) == 180
    assert len(cad_live) == len(cad_cached) == 180
    assert hr_live == hr_cached == hr_worker
    assert cad_live == cad_cached

    hr_hash = hashlib.sha256(bytes(f"{hr_live}".encode("utf-8"))).hexdigest()[:8]
    cad_hash = hashlib.sha256(bytes(f"{cad_live}".encode("utf-8"))).hexdigest()[:8]

    curr_hr = live_frame["extra_indicators"]["fit_heart_rate_text"][0]
    curr_cad = live_frame["extra_indicators"]["fit_cadence_text"][0]
    pos = live_frame["current_position"]

    print(
        f"sec={sec:5.1f} | frame={frame_idx:4d} | pos={pos:6.4f} | "
        f"HR_cnt={len(hr_live)} (hash={hr_hash}, curr={curr_hr}) | "
        f"CAD_cnt={len(cad_live)} (hash={cad_hash}, curr={curr_cad}) | "
        f"PARITY=100%"
    )

    # Render actual HUD overlay frame
    img = compose_overlay(
        canvas_w=1920,
        canvas_h=1080,
        layout=layout,
        font_path=font_path,
        **live_frame,
    )
    frame_path = out_dir / f"overlay_frame_{sec:05.1f}s.png"
    img.save(frame_path)
    print(f"  -> Saved frame render to {frame_path}")

print("\nETAP 8E Validation completed successfully.")
