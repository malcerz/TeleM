"""Trace indicator rendering step by step."""
import json
import sys
from pathlib import Path
from datetime import datetime, timezone, timedelta
from PIL import Image
import numpy as np

root = Path("c:/_DEV/TeleM")
sys.path.insert(0, str(root))
sys.path.insert(0, str(root / "src"))

from src.indicators.compositor import compose_overlay, render_preview
from src.indicators.frame_data import prepare_overlay_frame_data
from src.indicators.time_block import render_time_block
from src.gui.telemetry_manager import TelemetryDataManager

def trace_all():
    layout_path = root / "def_layout.json"
    layout = json.load(open(layout_path, encoding="utf-8"))
    
    video_path = root / "Video" / "GX030120.MP4"
    json_path = root / "Video" / "GX030120.json"
    fit_path = root / "Video" / "Popoludniowa_jazda_na_rowerze_solar_battery.fit"
    
    tm = TelemetryDataManager()
    tm.load_telemetry(str(video_path), str(json_path), str(fit_path))
    
    print(f"Telemetry start_dt_utc: {tm.start_dt_utc}")
    print(f"ISO samples count: {len(tm.iso_samples) if tm.iso_samples else 0}")
    print(f"Exposure samples count: {len(tm.exposure_samples) if tm.exposure_samples else 0}")
    print(f"Temperature samples count: {len(tm.temperature_samples) if tm.temperature_samples else 0}")
    print(f"Speed samples count: {len(tm.speed_samples) if tm.speed_samples else 0}")
    
    # Check GPMF sample inventory in raw json
    raw_gpmf = json.load(open(json_path, encoding="utf-8"))
    print("Raw GPMF top-level keys / devices:", list(raw_gpmf.keys()))
    
    # Target dt
    target_dt = tm.start_dt_utc or datetime.now(timezone.utc)
    
    # 1. Test render_time_block directly
    font_path = "C:/_DEV/TeleM/resources/fonts/Roboto-Bold.ttf"
    tb_img, tbx, tby = render_time_block(3840, 2160, layout, font_path, "2026-08-19", "12:00:00")
    print(f"Direct render_time_block: img={tb_img}, pos=({tbx}, {tby})")
    
    # 2. Test prepare_overlay_frame_data
    frame_data = prepare_overlay_frame_data(
        layout=layout,
        target_dt=target_dt,
        tz_offset_hours=2.0,
        start_dt_utc=tm.start_dt_utc,
        speed_samples=tm.speed_samples or [],
        track_samples=tm.track_samples or [],
        alt_samples=tm.alt_samples or [],
        iso_samples=tm.iso_samples,
        exposure_samples=tm.exposure_samples,
        temperature_samples=tm.temperature_samples,
        fit_data=tm.fit_data,
        gps_track=tm.get_gps_track_for_source("fit"),
        total_frames=60,
        current_index=0,
        resolve_cache_value=lambda k, src, dt, indicator_key=None: tm.resolve_value(
            k, dt, source=src, indicator_key=indicator_key
        ),
    )
    print("\nframe_data extracted values:")
    print(f"  date_text: {frame_data.get('date_text')}")
    print(f"  time_text: {frame_data.get('time_text')}")
    print(f"  iso_value: {frame_data.get('iso_value')}")
    print(f"  exposure_value: {frame_data.get('exposure_value')}")
    print(f"  temp_value: {frame_data.get('temp_value')}")
    print(f"  extra_indicators keys: {list(frame_data.get('extra_indicators', {}).keys())}")
    for k in ["iso_text", "exposure_text", "temp_text", "fit_temperature_text"]:
        if k in frame_data.get("extra_indicators", {}):
            print(f"    extra_indicators[{k}] = {frame_data['extra_indicators'][k]}")
    
    # 3. Test compose_overlay
    bboxes = {}
    overlay = compose_overlay(
        3840, 2160,
        layout,
        font_path,
        frame_data["date_text"],
        frame_data["time_text"],
        frame_data["speed_value"],
        frame_data["distance_m"],
        frame_data["max_distance_m"],
        frame_data["alt_value"],
        frame_data["min_alt"],
        frame_data["max_alt"],
        frame_data["iso_value"],
        frame_data["exposure_value"],
        frame_data["temp_value"],
        indicator_values=frame_data["indicator_values"],
        max_speed_kmh=frame_data["max_speed_kmh"],
        power_value=frame_data["power_value"],
        atemp_value=frame_data["atemp_value"],
        hr_value=frame_data["hr_value"],
        cad_value=frame_data["cad_value"],
        battery_value=frame_data["battery_value"],
        _bboxes=bboxes,
        extra_indicators=frame_data["extra_indicators"],
        chart_data=frame_data["chart_data"],
        gps_track=frame_data["gps_track"],
        target_dt=frame_data["target_dt"],
        start_dt_utc=frame_data["start_dt_utc"],
    )
    print("\ncompose_overlay result:")
    print(f"  Rendered bboxes: {list(bboxes.keys())}")
    for k, bb in bboxes.items():
        print(f"    - {k}: {bb}")

if __name__ == "__main__":
    trace_all()
