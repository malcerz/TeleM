"""ETAP 2E TEST 2 — lean_indicator variability over 120 consecutive frames.

Rebuilds the FINAL-render telemetry pipeline for the real user project
(GX030120 + def_layout.json) exactly like the AMD exporter does:
init_worker(field_samples=...) -> build_telemetry_cache(...) -> lookup(idx)
and prints, per frame:
  source telemetry value (extra_indicators["lean_indicator"][0])
  computed lean angle    (lean_angle(value, cfg))
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.gui.telemetry_manager import TelemetryDataManager
from src.telemetry_processed_cache import read_processed_cache, apply_processed_cache
from src.indicators.frame_data import build_active_fit_field_plan
from src.indicators.lean import lean_angle
from src.ffmpeg.worker_cache import init_worker
from src.telemetry_precompute import build_telemetry_cache

VIDEO = Path("Video/GX030120.MP4")
LAYOUT_PATH = Path("def_layout.json")
FRAMES = 120
FPS = 30000.0 / 1001.0


def main() -> None:
    layout = json.load(open(LAYOUT_PATH, encoding="utf-8"))
    cfg = layout["indicators"]["lean_indicator"]
    assert str(cfg.get("form")) == "lean" and cfg.get("enabled", True)

    tm = TelemetryDataManager()
    processed = read_processed_cache(VIDEO)
    assert processed is not None, "processed cache missing"
    apply_processed_cache(tm, processed)
    print(
        "IMU series: accel_x=%d gyro_x=%d"
        % (len(tm.accel_x_samples or []), len(tm.gyro_x_samples or []))
    )

    field_samples = {
        "speed_samples": tm.speed_samples,
        "track_samples": tm.track_samples,
        "alt_samples": tm.alt_samples,
        "heading_samples": tm.heading_samples,
        "gpx_heading_samples": tm.gpx_heading_samples,
        "slope_samples": tm.slope_samples,
        "gpx_slope_samples": tm.gpx_slope_samples,
        "iso_samples": tm.iso_samples,
        "exposure_samples": tm.exposure_samples,
        "temperature_samples": tm.temperature_samples,
        "accel_x_samples": tm.accel_x_samples,
        "accel_y_samples": tm.accel_y_samples,
        "accel_z_samples": tm.accel_z_samples,
        "accel_magnitude_samples": tm.accel_magnitude_samples,
        "gyro_x_samples": tm.gyro_x_samples,
        "gyro_y_samples": tm.gyro_y_samples,
        "gyro_z_samples": tm.gyro_z_samples,
        "gyro_magnitude_samples": tm.gyro_magnitude_samples,
    }

    fit_data = tm.fit_data or {}
    init_worker(
        video_width=3840,
        video_height=2160,
        font_path="",
        layout=layout,
        field_samples=field_samples,
        iso_samples=tm.iso_samples,
        exposure_samples=tm.exposure_samples,
        temperature_samples=tm.temperature_samples,
        fit_data=fit_data,
        gps_track=(tm.gps_track or []),
        start_dt_utc=tm.start_dt_utc,
        target_fps=FPS,
        total_overlay_frames=FRAMES,
    )

    cache = build_telemetry_cache(
        layout=layout,
        base_dt=tm.start_dt_utc,
        tz_offset_hours=2.0,
        start_dt_utc=tm.start_dt_utc,
        speed_samples=tm.speed_samples,
        track_samples=tm.track_samples,
        alt_samples=tm.alt_samples,
        iso_samples=tm.iso_samples,
        exposure_samples=tm.exposure_samples,
        temperature_samples=tm.temperature_samples,
        fit_data=fit_data,
        gps_track=tm.gps_track or [],
        chart_data={},
        resolve_cache_value=None,
        _range_cache={},
        fit_field_plan=build_active_fit_field_plan(layout, list(fit_data.keys())),
        total_frames=FRAMES,
        target_fps=FPS,
    )

    rows = []
    for idx in range(FRAMES):
        kw = cache.lookup(idx)
        raw = kw["extra_indicators"]["lean_indicator"][0]
        angle = lean_angle(raw, cfg)
        rows.append((idx, raw, angle))
        if idx < 10 or idx % 20 == 0:
            print(f"frame {idx:4d} | source roll = {raw!r:>22} | computed angle = {angle:+7.3f} deg")

    src_unique = len({repr(r[1]) for r in rows})
    ang_unique = len({round(r[2], 6) for r in rows})
    print("-" * 60)
    print(f"LEAN SOURCE VALUES UNIQUE: {src_unique}")
    print(f"LEAN COMPUTED ANGLES UNIQUE: {ang_unique}")
    print("LEAN MOVES:", "YES" if src_unique > 1 and ang_unique > 1 else "NO")


if __name__ == "__main__":
    main()
