"""
Verify mathematical and world->pixel geometry parity between 692 (with Lanczos) and native 691 (Direct).
"""
import math
import numpy as np
from PIL import Image
import sys
from pathlib import Path

root = Path("c:/_DEV/TeleM")
sys.path.insert(0, str(root))

from src.indicators.moving_map import render_map_working_image, _map_render_plan
from src.gui.layout_manager import normalize_layout
from src.gui.telemetry_manager import TelemetryDataManager
from src.telemetry_extract import (
    ensure_records_list, load_json_with_fallback,
    extract_speed_samples, extract_altitude_samples, extract_track_samples,
    extract_iso_samples, extract_exposure_samples, extract_temperature_samples,
    smooth_speed_samples, interpolate_value, get_rotation_from_metadata,
    get_container_rotation, find_metadata_json, extract_gps_track,
    smooth_speed_values, extract_accelerometer_samples, extract_gyroscope_samples,
)

v_1131 = root / "Video" / "GX020079.mp4"
fit_1131 = root / "Video" / "Morning_Ride.fit"

tm = TelemetryDataManager(
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
tm.load_gpmf_records(ensure_records_list(load_json_with_fallback(v_1131.with_suffix(".json"))))
tm.load_fit(str(fit_1131))
gps_track = tm.get_gps_track_for_source("fit")
layout = normalize_layout(root / "def_layout.json", 3840, 2160)

# Check render plan
print("=== RENDER PLAN CHECK ===")
plan_4k = _map_render_plan(3840, 691, 16)
print(f"4K plan: {plan_4k}")
plan_1080 = _map_render_plan(1920, 346, 16)
print(f"1080p plan: {plan_1080}")
plan_720 = _map_render_plan(1280, 230, 16)
print(f"720p plan: {plan_720}")
plan_480 = _map_render_plan(854, 154, 16)
print(f"480p plan: {plan_480}")

from src.moving_map import MovingMapRenderer
renderer_692 = MovingMapRenderer(gps_track, zoom=18, style="light_all")
renderer_691 = MovingMapRenderer(gps_track, zoom=18, style="light_all")

# Check marker center on 5 timestamps (0%, 25%, 50%, 75%, 100%)
dur = gps_track[-1][0].timestamp() - gps_track[0][0].timestamp()
check_fracs = [0.0, 0.25, 0.50, 0.75, 1.0]

print("\n=== MARKER CENTER DELTA CHECK ===")
for frac in check_fracs:
    ts = frac * dur
    cpx, cpy = renderer_692._interp_pos(ts)
    
    # 692 render -> center in tile grid
    # scx_692 = cpx - tx1*256
    # marker is at scx - x1_692 where x1_692 = int(scx - 692/2) = int(scx - 346)
    # when downscaled by 691/692: (scx - x1_692) * (691/692)
    # 691 render -> marker is at scx - x1_691 where x1_691 = int(scx - 691/2) = int(scx - 345.5)
    
    # Render actual images
    img_692 = renderer_692.render(ts, 692, 692)
    img_691 = renderer_691.render(ts, 691, 691)
    
    # Lanczos resize 692 -> 691
    img_692_down = img_692.resize((691, 691), Image.Resampling.LANCZOS)
    
    # Compare images
    arr_down = np.array(img_692_down)
    arr_direct = np.array(img_691)
    
    diff = np.abs(arr_down.astype(np.int16) - arr_direct.astype(np.int16))
    mae = float(np.mean(diff))
    max_d = int(np.max(diff))
    mse = float(np.mean(diff ** 2))
    psnr = 10.0 * math.log10(255.0 ** 2 / mse) if mse > 0 else 99.0
    
    print(f"Timestamp frac={frac*100:3.0f}%: MAE={mae:.4f}/255 ({mae/255*100:.3f}%), MAX={max_d}, PSNR={psnr:.2f} dB")
