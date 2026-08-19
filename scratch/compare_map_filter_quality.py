"""
Compare image quality between Map Resample filters (Lanczos3 vs Bicubic vs Bilinear vs Direct 1:1).
"""
import numpy as np
from PIL import Image
import math
import sys
from pathlib import Path

root = Path("c:/_DEV/TeleM")
sys.path.insert(0, str(root))
out_dir = root / "Raporty" / "etap8u_a_artifacts"

def sinc(x):
    if abs(x) < 1e-6:
        return 1.0
    return math.sin(math.pi * x) / (math.pi * x)

def lanczos3(x):
    if abs(x) >= 3.0:
        return 0.0
    return sinc(x) * sinc(x / 3.0)

def catmull_rom(x):
    a = -0.5
    ax = abs(x)
    if ax < 1.0:
        return (a + 2.0) * ax * ax * ax - (a + 3.0) * ax * ax + 1.0
    if ax < 2.0:
        return a * ax * ax * ax - 5.0 * a * ax * ax + 8.0 * a * ax - 4.0 * a
    return 0.0

def cpu_resample(img: Image.Image, dst_w: int, dst_h: int, filter_type: str) -> np.ndarray:
    src_arr = np.array(img, dtype=np.float32)
    src_h, src_w, _ = src_arr.shape
    scale_x = float(src_w) / float(dst_w)
    scale_y = float(src_h) / float(dst_h)
    
    out_arr = np.zeros((dst_h, dst_w, 4), dtype=np.float32)
    
    for y in range(dst_h):
        cy = (y + 0.5) * scale_y - 0.5
        for x in range(dst_w):
            cx = (x + 0.5) * scale_x - 0.5
            
            if filter_type == "bilinear":
                base_x = int(math.floor(cx))
                base_y = int(math.floor(cy))
                taps = 2
            elif filter_type == "bicubic":
                base_x = int(math.floor(cx)) - 1
                base_y = int(math.floor(cy)) - 1
                taps = 4
            else: # lanczos
                base_x = int(math.floor(cx)) - 2
                base_y = int(math.floor(cy)) - 2
                taps = 6
                
            premul_rgb = np.zeros(3, dtype=np.float32)
            alpha_acc = 0.0
            wsum = 0.0
            
            for dy in range(taps):
                iy = base_y + dy
                if filter_type == "bilinear":
                    wy = 1.0 - abs(cy - iy)
                elif filter_type == "bicubic":
                    wy = catmull_rom(cy - iy)
                else:
                    wy = lanczos3(cy - iy)
                if abs(wy) < 1e-6:
                    continue
                    
                for dx in range(taps):
                    ix = base_x + dx
                    if ix < 0 or ix >= src_w or iy < 0 or iy >= src_h:
                        continue
                    if filter_type == "bilinear":
                        wx = 1.0 - abs(cx - ix)
                    elif filter_type == "bicubic":
                        wx = catmull_rom(cx - ix)
                    else:
                        wx = lanczos3(cx - ix)
                    if abs(wx) < 1e-6:
                        continue
                        
                    w = wx * wy
                    s = src_arr[iy, ix]
                    premul_rgb += s[:3] * s[3] * w
                    alpha_acc += s[3] * w
                    wsum += w
                    
            if wsum > 1e-6 and alpha_acc > 1e-6:
                out_arr[y, x, :3] = premul_rgb / alpha_acc
                out_arr[y, x, 3] = alpha_acc / wsum
                
    return np.clip(out_arr, 0, 255).astype(np.uint8)

# Load actual map image
from src.indicators.moving_map import render_map_working_image
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

print("Rendering test map image (frame 300)...")
map_img, dst_bbox = render_map_working_image(
    3840, 2160, layout, "track_map", gps_track, current_position=300/1131.0
)

# Test Resample 692 -> 691
print("Computing Lanczos3 reference...")
lanczos_arr = cpu_resample(map_img, 691, 691, "lanczos")

print("Computing Bicubic CatmullRom...")
bicubic_arr = cpu_resample(map_img, 691, 691, "bicubic")

print("Computing Bilinear...")
bilinear_arr = cpu_resample(map_img, 691, 691, "bilinear")

# Direct crop 691x691 (center 1-px border drop)
direct_arr = np.array(map_img.crop((0, 0, 691, 691)))

def compare_metrics(ref, test, name):
    diff = np.abs(ref.astype(np.float32) - test.astype(np.float32))
    mae = float(np.mean(diff))
    max_d = int(np.max(diff))
    mse = float(np.mean(diff ** 2))
    psnr = 10.0 * math.log10(255.0 ** 2 / mse) if mse > 0 else 99.0
    print(f"\n--- {name} vs Lanczos3 Reference ---")
    print(f"MAE:  {mae:.6f} / 255 ({mae/255.0*100:.4f}%)")
    print(f"MAX:  {max_d} / 255")
    print(f"PSNR: {psnr:.2f} dB")
    return mae, max_d, psnr

compare_metrics(lanczos_arr, bicubic_arr, "Bicubic Catmull-Rom")
compare_metrics(lanczos_arr, bilinear_arr, "Bilinear")
compare_metrics(lanczos_arr, direct_arr, "Direct 1:1 Crop (No Resample)")

# Save Visual Artifacts
Image.fromarray(lanczos_arr).save(out_dir / "map_filter_lanczos.png")
Image.fromarray(bicubic_arr).save(out_dir / "map_filter_bicubic.png")
Image.fromarray(bilinear_arr).save(out_dir / "map_filter_bilinear.png")
Image.fromarray(direct_arr).save(out_dir / "map_filter_direct1to1.png")

# Save diff heatmaps
diff_bilinear = np.clip(np.abs(lanczos_arr.astype(np.int16) - bilinear_arr.astype(np.int16)) * 10, 0, 255).astype(np.uint8)
diff_direct = np.clip(np.abs(lanczos_arr.astype(np.int16) - direct_arr.astype(np.int16)) * 10, 0, 255).astype(np.uint8)
Image.fromarray(diff_bilinear).save(out_dir / "map_diff_bilinear_x10.png")
Image.fromarray(diff_direct).save(out_dir / "map_diff_direct_x10.png")

print(f"\nVisual comparison images saved to {out_dir}")
