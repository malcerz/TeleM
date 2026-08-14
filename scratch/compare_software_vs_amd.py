import os
import sys
import json
from datetime import datetime, timedelta

sys.path.insert(0, os.path.abspath("."))
from src.gui.telemetry_manager import TelemetryDataManager
from src.ffmpeg.worker_cache import init_worker, _resolve_cache_value
from src.indicators.frame_data import prepare_overlay_frame_data

video_path = os.path.abspath("Video/GX020079.mp4")
fit_path = os.path.abspath("Video/Morning_Ride.fit")
layout_path = os.path.abspath("def_layout.json")
font_path = os.path.abspath("include/fonts/Roboto-Bold.ttf")

with open(layout_path, "r", encoding="utf-8") as f:
    layout = json.load(f)

tm = TelemetryDataManager()
tm.load_fit(fit_path)

init_worker(
    video_width=3840,
    video_height=2160,
    font_path=font_path,
    layout=layout,
    field_samples={},
    fit_data=tm.fit_data,
    gps_track=tm.fit_gps_track,
)

target_dt = (tm.start_dt_utc or datetime.now()) + timedelta(seconds=30 / 29.97)

frame_kwargs = prepare_overlay_frame_data(
    layout=layout,
    target_dt=target_dt,
    tz_offset_hours=2.0,
    start_dt_utc=tm.start_dt_utc,
    speed_samples=[],
    track_samples=[],
    alt_samples=[],
    fit_data=tm.fit_data,
    gps_track=tm.fit_gps_track,
    resolve_cache_value=_resolve_cache_value,
)

print("=================================================================")
print("  FRAME 30 TELEMETRY DATA COMPARISON                             ")
print("=================================================================")
print(f"Speed value:      {frame_kwargs.get('speed_value'):.2f} km/h")
print(f"Heart rate (HR):  {frame_kwargs.get('hr_value'):.1f} BPM")
print(f"Cadence (CAD):    {frame_kwargs.get('cad_value'):.1f} RPM")
print(f"Power:            {frame_kwargs.get('power_value'):.1f} W")
print(f"Altitude (Alt):   {frame_kwargs.get('alt_value'):.1f} m")
print(f"Distance:         {frame_kwargs.get('distance_m'):.1f} m")
print(f"Extra Indicators: {frame_kwargs.get('extra_indicators')}")
print("=================================================================")
