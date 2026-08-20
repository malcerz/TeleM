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
from src.indicators.frame_data import prepare_overlay_frame_data
from src.telemetry_precompute import build_telemetry_cache
from src.overlay_renderer import compose_overlay
from src.ffmpeg.worker_cache import init_worker, WORKER_CACHE, _resolve_cache_samples, _get_source_samples, _resolve_cache_value
from src.indicators.chart import _render_chart_indicator

# Load GX030120 data
json_path = Path("Video/GX030120.json")
fit_path = Path("Video/Poranna_jazda_na_rowerze.fit")

raw_records = ensure_records_list(load_json_with_fallback(json_path))
anchor_dt = find_gps_anchor(raw_records)
print(f"GX030120 GPS Anchor: {anchor_dt}")

fit_data = process_fit(str(fit_path), video_start_dt=anchor_dt)
print("FIT keys:", list(fit_data.keys()))

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

# Check chart indicators in layout
for k, v in layout["indicators"].items():
    if v.get("form") == "chart":
        print(f"Chart indicator: {k:25s} | enabled={v.get('enabled')} | src={v.get('source')} | scope={v.get('chart_time_scope', 'activity')}")

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

# Test frame 0, 1000, 2500, 5000
test_frame_indices = [0, 1000, 2700, 5399]

out_dir = Path("scratch/chart_debug")
out_dir.mkdir(parents=True, exist_ok=True)

# Build precompute cache
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
    chart_data=WORKER_CACHE["_prep_cache"].get("chart_data"),
    _range_cache=WORKER_CACHE["_prep_cache"],
    total_frames=5400,
    target_fps=29.97,
)

print(f"\nComparing PRECOMPUTE OFF vs PRECOMPUTE ON:")
for f_idx in test_frame_indices:
    # 1. PRECOMPUTE OFF
    target_dt = anchor_dt + timedelta(seconds=f_idx / 29.97)
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
        current_index=f_idx,
        chart_data=WORKER_CACHE.get("_precomputed_chart_data"),
        resolve_cache_value=_resolve_cache_value,
        _range_cache=WORKER_CACHE.get("_prep_cache"),
    )
    
    # 2. PRECOMPUTE ON
    fd_on = precompute_cache.lookup(f_idx)

    # Check chart data in fd_off vs fd_on
    cd_off = fd_off.get("chart_data", {})
    cd_on = fd_on.get("chart_data", {})
    
    print(f"\n--- FRAME {f_idx} ---")
    for ch_key in ("fit_cadence_text", "fit_heart_rate_text"):
        ch_off = cd_off.get(ch_key)
        ch_on = cd_on.get(ch_key)
        
        len_off = len(ch_off) if ch_off else 0
        len_on = len(ch_on) if ch_on else 0
        ts_off = getattr(ch_off, "timestamps", None)
        ts_on = getattr(ch_on, "timestamps", None)
        st_off = getattr(ch_off, "chart_start_dt", None)
        st_on = getattr(ch_on, "chart_start_dt", None)
        et_off = getattr(ch_off, "chart_end_dt", None)
        et_on = getattr(ch_on, "chart_end_dt", None)
        print(f"  {ch_key}:")
        print(f"    OFF: len={len_off} | start={st_off} | end={et_off} | ts_len={len(ts_off) if ts_off else 0}")
        print(f"    ON:  len={len_on} | start={st_on} | end={et_on} | ts_len={len(ts_on) if ts_on else 0}")
        
        if ch_off and len(ch_off) > 0:
            print(f"    OFF sample range: min={min(ch_off)} max={max(ch_off)} first={ch_off[0]} last={ch_off[-1]}")
            if ts_off:
                print(f"    OFF ts range: first={ts_off[0]} last={ts_off[-1]}")

    # Render frame with compose_overlay
    img_off = compose_overlay(
        1920, 1080, layout, font_path="",
        **fd_off
    )
    img_on = compose_overlay(
        1920, 1080, layout, font_path="",
        **fd_on
    )

    img_off.save(out_dir / f"frame_{f_idx}_off.png")
    img_on.save(out_dir / f"frame_{f_idx}_on.png")

    # Pixel diff between OFF and ON
    arr_off = np.array(img_off)
    arr_on = np.array(img_on)
    diff = np.abs(arr_off.astype(np.int32) - arr_on.astype(np.int32))
    max_d = np.max(diff)
    diff_px = np.count_nonzero(diff)
    print(f"  Pixel diff OFF vs ON: max_diff={max_d}, diff_pixels={diff_px}")

print("\nSaved debug images to scratch/chart_debug/")
