"""Test hypothesis for ETAP 8D (2.28 ms) vs ETAP 8F (11.3 ms)."""
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
import numpy as np

root = Path("c:/_DEV/TeleM")
sys.path.insert(0, str(root))

from src.indicators.compositor import compose_overlay
from src.indicators import chart as chart_module
from src.indicators import chart_utils as chart_utils_module
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
from src.ffmpeg.worker_cache import init_worker, WORKER_CACHE

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

layout = json.load(open(root / "def_layout.json", encoding="utf-8"))
font_path = "arial.ttf"

def test_config(name: str, start_dt: datetime):
    print(f"\n==========================================")
    print(f"=== TESTING CONFIG: {name} (start_dt={start_dt}) ===")
    print(f"==========================================")
    
    init_worker(
        video_width=3840,
        video_height=2160,
        font_path=font_path,
        layout=layout,
        field_samples={"speed_samples": tm.speed_samples, "track_samples": tm.track_samples, "alt_samples": tm.alt_samples},
        speed_samples=smooth_speed_samples(tm.speed_samples, "moving_average", 5),
        track_samples=tm.track_samples,
        alt_samples=smooth_speed_samples(tm.alt_samples, "moving_average", 5),
        fit_data=tm.fit_data,
        total_overlay_frames=900,
        target_fps=29.97,
        start_dt_utc=start_dt,
    )
    chart_data = WORKER_CACHE.get("_precomputed_chart_data", {})
    
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
        chart_data=chart_data,
        total_frames=900,
        target_fps=29.97,
    )

    fk0 = cache.lookup(0)
    print(f"Frame 0 values: hr={fk0.get('hr_value')}, cad={fk0.get('cad_value')}, extra={list(fk0.get('extra_indicators', {}).keys())}")
    for k in ["fit_cadence_text", "fit_heart_rate_text", "fit_enhanced_speed_text"]:
        print(f"  {k}: {fk0.get('extra_indicators', {}).get(k)}")

    gpu_chart_keys = {"fit_cadence_text", "fit_heart_rate_text"}
    times = []
    
    # Warm up 5 frames
    for f in range(5):
        _bboxes = {}
        gpu_capture = {}
        compose_overlay(
            canvas_w=3840, canvas_h=2160, layout=layout, font_path=font_path,
            _bboxes=_bboxes, gpu_capture_keys=gpu_chart_keys, gpu_capture=gpu_capture,
            split_chart_keys=gpu_chart_keys, **cache.lookup(f)
        )
    
    # Measure 100 frames
    for f in range(5, 105):
        fk = cache.lookup(f)
        _bboxes = {}
        gpu_capture = {}
        t0 = time.perf_counter()
        compose_overlay(
            canvas_w=3840, canvas_h=2160, layout=layout, font_path=font_path,
            _bboxes=_bboxes, gpu_capture_keys=gpu_chart_keys, gpu_capture=gpu_capture,
            split_chart_keys=gpu_chart_keys, **fk
        )
        t1 = time.perf_counter()
        times.append((t1 - t0) * 1000.0)

    print(f"Rendered bboxes on frame 50: {list(_bboxes.keys())}")
    print(f"gpu_capture on frame 50: {list(gpu_capture.keys())}")
    print(f"Timing (100 frames): median={np.median(times):.3f} ms, p95={np.percentile(times, 95):.3f} ms, mean={np.mean(times):.3f} ms, min={np.min(times):.3f} ms, max={np.max(times):.3f} ms")


# Test 1: ETAP 8D setup (timestamp outside FIT -> all FIT None)
test_config("ETAP 8D (all FIT None)", datetime(2026, 8, 5, 4, 28, 11))

# Test 2: ETAP 8F setup (timestamp inside FIT -> all FIT Active)
test_config("ETAP 8F (all FIT Active)", tm.speed_samples[0][0])
