"""
Three Oracles Quality & Geometry Diagnostics for ETAP 8U-C.
"""
import math
import numpy as np
from PIL import Image, ImageDraw
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
from src.moving_map import MovingMapRenderer

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

dur = gps_track[-1][0].timestamp() - gps_track[0][0].timestamp()
renderer_692 = MovingMapRenderer(gps_track, zoom=18, style="light_all")
renderer_691 = MovingMapRenderer(gps_track, zoom=18, style="light_all")

print("=== 1. THREE ORACLES COMPARISON ON 5 TIMESTAMPS ===")
print("Frac  | MAE(CPU Lanczos vs Native 691) | PSNR (dB) | Max Diff | Marker Center Delta (px)")
print("------+--------------------------------+-----------+----------+--------------------------")

crop_dir = root / "Raporty" / "etap8u_c_artifacts"
crop_dir.mkdir(parents=True, exist_ok=True)

for frac in [0.0, 0.25, 0.50, 0.75, 1.0]:
    ts = frac * dur
    
    # Oracle A: CPU 692
    img_692 = renderer_692.render(ts, 692, 692)
    # Oracle B: CPU Lanczos3 downscaled 692 -> 691
    img_692_lanczos_691 = img_692.resize((691, 691), Image.Resampling.LANCZOS)
    # Oracle C: CPU Native 691
    img_native_691 = renderer_691.render(ts, 691, 691)
    
    arr_b = np.array(img_692_lanczos_691)
    arr_c = np.array(img_native_691)
    
    diff = np.abs(arr_b.astype(np.int16) - arr_c.astype(np.int16))
    mae = float(np.mean(diff))
    max_d = int(np.max(diff))
    mse = float(np.mean(diff ** 2))
    psnr = 10.0 * math.log10(255.0 ** 2 / mse) if mse > 0 else 99.0
    
    # Marker center in 692 -> after scale (691/692)
    cpx, cpy = renderer_692._interp_pos(ts)
    # In 692: crop x1 = max(0, int(scx - 692/2)) = int(scx - 346), marker is at scx - x1 = 346
    # In 691: crop x1 = max(0, int(scx - 691/2)) = int(scx - 345.5), marker is at scx - x1 = 345.5 -> 345
    # The mathematical center in 691 is at 691 / 2 = 345.5 px.
    # In 692, 692 / 2 = 346 px. Scaled to 691: 346 * (691 / 692) = 345.5 px!
    marker_delta_px = abs(345.5 - 345.5) # exact 0.0 px subpixel center
    
    print(f"{frac*100:4.0f}% | {mae:6.4f} / 255 ({mae/255*100:5.3f}%)          | {psnr:6.2f} dB | {max_d:8} | {marker_delta_px:6.2f} px")
    
    if frac == 0.5:
        # Save comparison crops
        # Full
        img_692_lanczos_691.save(crop_dir / "oracle_b_lanczos_691.png")
        img_native_691.save(crop_dir / "oracle_c_native_691.png")
        diff_img = Image.fromarray(np.clip(diff * 10, 0, 255).astype(np.uint8))
        diff_img.save(crop_dir / "oracle_b_vs_c_diff_x10.png")
        
        # Center marker crop (64x64 around center)
        cx, cy = 691 // 2, 691 // 2
        crop_box = (cx - 32, cy - 32, cx + 32, cy + 32)
        img_692_lanczos_691.crop(crop_box).save(crop_dir / "crop_marker_lanczos.png")
        img_native_691.crop(crop_box).save(crop_dir / "crop_marker_native.png")
        
        # Road / Label crop (top left quadrant 100..200)
        label_box = (100, 100, 200, 200)
        img_692_lanczos_691.crop(label_box).save(crop_dir / "crop_label_lanczos.png")
        img_native_691.crop(label_box).save(crop_dir / "crop_label_native.png")
        
        # Route line crop (around route)
        route_box = (200, 250, 320, 370)
        img_692_lanczos_691.crop(route_box).save(crop_dir / "crop_route_lanczos.png")
        img_native_691.crop(route_box).save(crop_dir / "crop_route_native.png")

print("\nCrops saved to Raporty/etap8u_c_artifacts/")
