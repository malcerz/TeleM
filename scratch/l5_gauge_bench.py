"""ETAP 5L — micro-benchmark of the speed gauge CPU render cost (isolated)."""
from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

os.environ["AMD_OVERLAY_PROFILE"] = "1"

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.telemetry_extract import (
    ensure_records_list, extract_speed_samples, extract_altitude_samples,
    extract_track_samples, extract_iso_samples, extract_exposure_samples,
    extract_temperature_samples, interpolate_value, load_json_with_fallback,
    smooth_speed_samples,
)
from src.gui.telemetry_manager import TelemetryDataManager
from src.indicators.compositor import compose_overlay
from src.indicators.frame_data import prepare_overlay_frame_data, build_active_fit_field_plan
from src.indicators.profiling import get_overlay_profiler

GAUGE_KEY = "fit_enhanced_speed_text"


def main() -> int:
    N = 120
    records = ensure_records_list(load_json_with_fallback(ROOT / "Video" / "GX020079.json"))
    telemetry = TelemetryDataManager(
        extract_speed_fn=extract_speed_samples, extract_altitude_fn=extract_altitude_samples,
        extract_track_fn=extract_track_samples, extract_iso_fn=extract_iso_samples,
        extract_exposure_fn=extract_exposure_samples, extract_temperature_fn=extract_temperature_samples,
        smooth_fn=smooth_speed_samples, interpolate_fn=interpolate_value,
    )
    telemetry.load_gpmf_records(records)
    telemetry.load_fit(ROOT / "Video" / "Morning_Ride.fit")
    telemetry.start_dt_utc = datetime(2026, 8, 5, 4, 28, 11)
    with (ROOT / "def_layout.json").open(encoding="utf-8") as fh:
        layout = json.load(fh)
    compose_layout = json.loads(json.dumps(layout))
    compose_layout["indicators"].pop("track_map", None)
    speed = smooth_speed_samples(telemetry.speed_samples, "moving_average", 5)
    altitude = smooth_speed_samples(telemetry.alt_samples, "moving_average", 5)
    track = telemetry.track_samples
    gps_track = telemetry.get_gps_track_for_source(layout["indicators"]["track_map"].get("source", "fit"))
    fit_field_plan = build_active_fit_field_plan(layout, (telemetry.fit_data or {}).keys())
    W, H = 3840, 2160
    fps = 30000 / 1001
    base_dt = telemetry.start_dt_utc
    font_path = str(ROOT / "include" / "mpv")
    profiler = get_overlay_profiler()

    def frame_kwargs(idx):
        return prepare_overlay_frame_data(
            layout=compose_layout, target_dt=base_dt + timedelta(seconds=idx / fps),
            start_dt_utc=base_dt, tz_offset_hours=2, speed_samples=speed,
            track_samples=track, alt_samples=altitude, iso_samples=telemetry.iso_samples,
            exposure_samples=telemetry.exposure_samples,
            temperature_samples=telemetry.temperature_samples,
            gpx_speed_samples=telemetry.gpx_speed_samples,
            gpx_track_samples=telemetry.gpx_track_samples,
            gpx_alt_samples=telemetry.gpx_alt_samples,
            gpx_power_samples=telemetry.gpx_power_samples,
            gpx_atemp_samples=telemetry.gpx_atemp_samples,
            gpx_hr_samples=telemetry.gpx_hr_samples,
            gpx_cad_samples=telemetry.gpx_cad_samples,
            fit_data=telemetry.fit_data, gps_track=gps_track, total_frames=1131,
            current_index=idx, chart_data={}, fit_field_plan=fit_field_plan,
        )

    for idx in range(5):
        compose_overlay(canvas_w=W, canvas_h=H, layout=compose_layout, font_path=font_path,
                        _bboxes={}, reuse_canvas=False, **frame_kwargs(idx))

    # CPU_REFERENCE gauge (gauge pasted) vs GPU gauge (captured, not pasted).
    started = time.perf_counter()
    for idx in range(N):
        profiler.start_frame(idx, W, H)
        compose_overlay(canvas_w=W, canvas_h=H, layout=compose_layout, font_path=font_path,
                        _bboxes={}, reuse_canvas=False, **frame_kwargs(idx % 1131))
        profiler.finish_frame()
    cpu_total = (time.perf_counter() - started) * 1000.0 / N

    started = time.perf_counter()
    for idx in range(N):
        profiler.start_frame(idx, W, H)
        cap = {}
        compose_overlay(canvas_w=W, canvas_h=H, layout=compose_layout, font_path=font_path,
                        _bboxes={}, gpu_capture_keys={GAUGE_KEY}, gpu_capture=cap,
                        reuse_canvas=False, **frame_kwargs(idx % 1131))
        profiler.finish_frame()
    gpu_total = (time.perf_counter() - started) * 1000.0 / N

    summary = profiler.summary()
    metrics = summary.get("metrics", {})
    print(f"compose_overlay CPU_REFERENCE gauge: {cpu_total:.3f} ms/frame")
    print(f"compose_overlay GPU-capture gauge:   {gpu_total:.3f} ms/frame")
    for key in ("indicator.fit_enhanced_speed_text.render", "compose.total"):
        if key in metrics:
            s = metrics[key]
            print(f"  {key}: avg={s.get('avg_ms', 0):.4f} ms median={s.get('median_ms', 0):.4f} ms")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
