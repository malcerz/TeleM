import sys
from pathlib import Path
_root = Path(__file__).resolve().parent.parent
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

from src.gui.layout_manager import normalize_layout
from src.indicators.compositor import compose_overlay
from telemetry_fit import process_fit
from src.telemetry_gpmf_new import gpmf_to_exiftool_json
from src.telemetry_extract import (
    extract_speed_samples, extract_altitude_samples, extract_track_samples,
    extract_iso_samples, extract_exposure_samples, extract_temperature_samples,
    find_gps_anchor
)

v_file = Path('Video/GX020079.mp4')
fit_file = Path('Video/Morning_Ride.fit')
records = gpmf_to_exiftool_json(str(v_file))[0]
speed_samples = extract_speed_samples(records)
alt_samples = extract_altitude_samples(records)
track_samples = extract_track_samples(records)
iso_samples = extract_iso_samples(records)
exposure_samples = extract_exposure_samples(records)
temp_samples = extract_temperature_samples(records)
anchor_dt = find_gps_anchor(records)
fit_data = process_fit(str(fit_file), video_start_dt=anchor_dt)
layout = normalize_layout(None, 1920, 1080)

# Render frame 0 to check pixel bbox
img0 = compose_overlay(
    1920, 1080, layout, "",
    "2026-08-05", "04:55:50",
    25.0, 500.0, 5000.0,
    150.0, 50.0, 300.0,
    100.0, 500.0, 25.0,
    indicator_values={
        "speed_visual": 25.0, "speed_text": 25.0, "dist_visual": 500.0, "dist_text": 0.5,
        "alt_visual": 150.0, "alt_text": 150.0, "iso_text": 100.0, "exposure_text": 500.0,
        "temp_text": 25.0, "power_text": 200.0, "atemp_text": 22.0, "hr_text": 140.0,
        "cad_text": 85.0, "battery_text": 90.0,
    },
    gps_track=fit_data.get("track"),
    target_dt=anchor_dt,
)

bbox_actual = img0.getbbox()
print(f"Actual non-zero pixel bbox for default layout: {bbox_actual}")
if bbox_actual:
    w = bbox_actual[2] - bbox_actual[0]
    h = bbox_actual[3] - bbox_actual[1]
    print(f"Width: {w}, Height: {h}, Area %: {(w * h) / (1920 * 1080) * 100:.1f}%")

# Let's test bottom-only layout (e.g. only speed, dist, alt at bottom)
bottom_layout = normalize_layout(None, 1920, 1080)
for k, v in bottom_layout["indicators"].items():
    if k not in ("speed_visual", "speed_text", "dist_visual", "dist_text", "alt_visual", "alt_text"):
        v["enabled"] = False

img_bottom = compose_overlay(
    1920, 1080, bottom_layout, "",
    "", "",
    25.0, 500.0, 5000.0,
    150.0, 50.0, 300.0,
    100.0, 500.0, 25.0,
    indicator_values={
        "speed_visual": 25.0, "speed_text": 25.0, "dist_visual": 500.0, "dist_text": 0.5,
        "alt_visual": 150.0, "alt_text": 150.0,
    },
)
bbox_bottom = img_bottom.getbbox()
print(f"\nBottom-only layout actual bbox: {bbox_bottom}")
if bbox_bottom:
    wb = bbox_bottom[2] - bbox_bottom[0]
    hb = bbox_bottom[3] - bbox_bottom[1]
    print(f"Width: {wb}, Height: {hb}, Area %: {(wb * hb) / (1920 * 1080) * 100:.1f}%")
