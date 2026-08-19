"""Verify impact of AMD_OVERLAY_PROFILE=1 on compose_overlay."""
import json
import os
import sys
import time
from pathlib import Path
import numpy as np

sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")

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
start_dt_real = tm.speed_samples[0][0]

layout = json.load(open(root / "def_layout.json", encoding="utf-8"))
font_path = "arial.ttf"

def test_profile_mode(profile_on: bool):
    os.environ["AMD_OVERLAY_PROFILE"] = "1" if profile_on else "0"
    
    from src.indicators.profiling import get_overlay_profiler
    profiler = get_overlay_profiler()
    profiler.enabled = profile_on
    if profile_on:
        profiler.install_pillow_hooks()

    from src.indicators.compositor import compose_overlay
    from src.telemetry_precompute import build_telemetry_cache
    from src.ffmpeg.worker_cache import init_worker, WORKER_CACHE
    from src.ffmpeg.amd_native_exporter import _ordered_map_layout_parts

    below_layout, _, _ = _ordered_map_layout_parts(layout)

    init_worker(
        video_width=3840, video_height=2160, font_path=font_path, layout=below_layout,
        field_samples={"speed_samples": tm.speed_samples, "track_samples": tm.track_samples, "alt_samples": tm.alt_samples},
        speed_samples=smooth_speed_samples(tm.speed_samples, "moving_average", 5),
        track_samples=tm.track_samples, alt_samples=smooth_speed_samples(tm.alt_samples, "moving_average", 5),
        fit_data=tm.fit_data, total_overlay_frames=900, target_fps=29.97, start_dt_utc=start_dt_real,
    )
    chart_data = WORKER_CACHE.get("_precomputed_chart_data", {})
    cache = build_telemetry_cache(
        layout=below_layout, base_dt=start_dt_real, tz_offset_hours=0.0, start_dt_utc=start_dt_real,
        speed_samples=smooth_speed_samples(tm.speed_samples, "moving_average", 5),
        track_samples=tm.track_samples, alt_samples=smooth_speed_samples(tm.alt_samples, "moving_average", 5),
        iso_samples=tm.iso_samples, exposure_samples=tm.exposure_samples, temperature_samples=tm.temperature_samples,
        fit_data=tm.fit_data, gps_track=tm.get_gps_track_for_source("fit"), chart_data=chart_data,
        total_frames=900, target_fps=29.97,
    )

    gpu_chart_keys = {"fit_cadence_text", "fit_heart_rate_text"}
    times = []
    
    # 200 frames
    for f in range(200):
        if profile_on:
            profiler.start_frame(f, 3840, 2160)
        fk = cache.lookup(f)
        _bboxes = {}
        gpu_capture = {}
        t0 = time.perf_counter()
        compose_overlay(
            canvas_w=3840, canvas_h=2160, layout=below_layout, font_path=font_path,
            _bboxes=_bboxes, gpu_capture_keys=gpu_chart_keys, gpu_capture=gpu_capture,
            split_chart_keys=gpu_chart_keys, reuse_canvas=True, **fk
        )
        t1 = time.perf_counter()
        times.append((t1 - t0) * 1000.0)

    print(f"AMD_OVERLAY_PROFILE={'1' if profile_on else '0'}:")
    print(f"  compose_overlay (200 frames): median={np.median(times):.3f} ms, p95={np.percentile(times, 95):.3f} ms, mean={np.mean(times):.3f} ms")


if __name__ == "__main__":
    # Test OFF
    test_profile_mode(False)
    # Test ON
    test_profile_mode(True)
