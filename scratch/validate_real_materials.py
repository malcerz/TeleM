"""Validation script for ETAP 8M.4 on real material GX020079.mp4 and Morning_Ride.fit."""
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from PIL import Image

root = Path("c:/_DEV/TeleM")
sys.path.insert(0, str(root))
sys.path.insert(0, str(root / "src"))

from src.gui.telemetry_manager import TelemetryDataManager
from src.telemetry_extract import (
    ensure_records_list, load_json_with_fallback,
    extract_speed_samples, extract_altitude_samples, extract_track_samples,
    extract_iso_samples, extract_exposure_samples, extract_temperature_samples,
    smooth_speed_samples, interpolate_value, get_rotation_from_metadata,
    get_container_rotation, find_metadata_json, extract_gps_track,
    smooth_speed_values, extract_accelerometer_samples, extract_gyroscope_samples,
)
from src.indicators.chart_builder import build_chart_data
from src.indicators.frame_data import prepare_overlay_frame_data
from src.indicators.compositor import compose_overlay
from src.indicators.chart_utils import get_history_chart_background

# 1. Load telemetry
telemetry = TelemetryDataManager(
    extract_speed_fn=extract_speed_samples,
    extract_altitude_fn=extract_altitude_samples,
    extract_track_fn=extract_track_samples,
    extract_iso_fn=extract_iso_samples,
    extract_exposure_fn=extract_exposure_samples,
    extract_temperature_fn=extract_temperature_samples,
    smooth_fn=smooth_speed_samples,
    interpolate_fn=interpolate_value,
    get_rotation_meta_fn=get_rotation_from_metadata,
    get_container_rotation_fn=get_container_rotation,
    find_meta_json_fn=find_metadata_json,
    find_meta_json_write_fn=lambda p: p.with_suffix(".json"),
    load_telemetry_fn=lambda *a: None,
    ensure_records_fn=ensure_records_list,
    load_json_fallback_fn=load_json_with_fallback,
    write_records_fn=lambda p, r: None,
    extract_samples_exiftool_fn=lambda f: [],
    extract_altitude_exiftool_fn=lambda f: [],
    extract_gps_track_fn=extract_gps_track,
    find_gps_anchor_fn=lambda r: None,
    smooth_values_fn=smooth_speed_values,
    extract_accelerometer_fn=extract_accelerometer_samples,
    extract_gyroscope_fn=extract_gyroscope_samples,
)

records = ensure_records_list(load_json_with_fallback(root / "Video" / "GX020079.json"))
telemetry.load_gpmf_records(records)
telemetry.load_fit(str(root / "Video" / "Morning_Ride.fit"))

video_dur = 37.74
start_dt = telemetry.start_dt_utc
end_dt = start_dt + timedelta(seconds=video_dur)

all_fit_pts = [s for s in telemetry.fit_data.values() if s]
fit_start = min(s[0][0] for s in all_fit_pts)
fit_end = max(s[-1][0] for s in all_fit_pts)
source_ranges = {"fit": (fit_start, fit_end)}

print(f"Video start: {start_dt}, end: {end_dt}, duration: {video_dur}s")
print(f"FIT start: {fit_start}, end: {fit_end}, duration: {(fit_end - fit_start).total_seconds()}s")

# Check points on timeline: start (0s), middle (18.87s), end (37.74s)
test_times = [
    ("start", 0.0),
    ("middle", 18.87),
    ("end", 37.74),
]

out_dir = root / "Raporty" / "etap8m4_artifacts"
out_dir.mkdir(parents=True, exist_ok=True)

for scope in ["activity", "video"]:
    layout = {
        "width": 1920, "height": 1080,
        "indicators": {
            "fit_cadence_text": {
                "enabled": True, "form": "chart", "source": "fit",
                "chart_time_scope": scope,
                "x": 10.0, "y": 70.0, "size": 30.0, "thickness": 2,
                "chart_color": "#00FF00", "fill_alpha": 50,
            },
            "fit_heart_rate_text": {
                "enabled": True, "form": "chart", "source": "fit",
                "chart_time_scope": scope,
                "x": 55.0, "y": 70.0, "size": 30.0, "thickness": 2,
                "chart_color": "#FF3333", "fill_alpha": 50,
            },
        }
    }

    chart_data = build_chart_data(
        layout,
        telemetry.get_samples_for_source,
        lambda f, s, k=None: telemetry.resolve_samples(f, s, indicator_key=k),
        start_dt_utc=start_dt,
        end_dt_utc=end_dt,
        source_activity_ranges=source_ranges,
    )

    cad_history = chart_data["fit_cadence_text"]
    print(f"\n--- Scope: {scope.upper()} ---")
    print(f"Cadence chart points: {len(cad_history)}, start: {cad_history.chart_start_dt}, end: {cad_history.chart_end_dt}")

    for label, t_s in test_times:
        target_dt = start_dt + timedelta(seconds=t_s)
        t_align = target_dt.replace(tzinfo=None)
        
        # Mathematical marker calculation:
        c_start = cad_history.chart_start_dt.replace(tzinfo=None) if cad_history.chart_start_dt.tzinfo else cad_history.chart_start_dt
        c_end = cad_history.chart_end_dt.replace(tzinfo=None) if cad_history.chart_end_dt.tzinfo else cad_history.chart_end_dt
        math_pos = (t_align - c_start).total_seconds() / (c_end - c_start).total_seconds()
        math_pos = max(0.0, min(1.0, math_pos))

        frame_data = prepare_overlay_frame_data(
            layout=layout,
            target_dt=target_dt,
            tz_offset_hours=2,
            start_dt_utc=start_dt,
            speed_samples=telemetry.speed_samples or [],
            track_samples=telemetry.track_samples or [],
            alt_samples=telemetry.alt_samples or [],
            iso_samples=telemetry.iso_samples,
            exposure_samples=telemetry.exposure_samples,
            temperature_samples=telemetry.temperature_samples,
            fit_data=telemetry.fit_data,
            chart_data=chart_data,
        )

        overlay_img = compose_overlay(
            canvas_w=1920,
            canvas_h=1080,
            layout=layout,
            font_path="assets/Roboto-Bold.ttf",
            reuse_canvas=False,
            **frame_data,
        )

        out_path = out_dir / f"{scope}_{label}.png"
        overlay_img.save(out_path)

        # Let's compute pixel position of the marker on the rendered chart
        # Chart geometry in layout: x=10.0%, y=70.0%, size=30.0% of 1080 -> 324px
        # chart_w = 324, chart_h = 129
        # In chart_utils: axis_left_margin is ~35, axis_right_margin is ~10, plot_w = chart_w - 45 = 279
        # plot_x1 = 35. Left of chart on canvas is 10% of 1920 + 4 = 196
        # Cursor X on canvas = 196 + 35 + math_pos * 279
        chart_w = int(1080 * 0.30)
        plot_left_margin = 35
        plot_right_margin = 10
        plot_w = chart_w - plot_left_margin - plot_right_margin
        chart_x_canvas = int(1920 * 0.10) + 4
        pixel_x = chart_x_canvas + plot_left_margin + math_pos * plot_w

        print(f"[{scope.upper()} {label.upper()}] t={t_s:5.2f}s | target_dt={target_dt} | math_pos={math_pos:8.5f} ({math_pos*100:5.2f}%) | pixel_x={pixel_x:.1f}px -> saved {out_path.name}")
