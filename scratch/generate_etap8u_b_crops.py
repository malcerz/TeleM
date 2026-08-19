"""
Generate visual crops and compute quality metrics across 100 frames for ETAP 8U-B.
"""
import math
import numpy as np
from PIL import Image
import sys
from pathlib import Path

root = Path("c:/_DEV/TeleM")
sys.path.insert(0, str(root))

from src.indicators.moving_map import render_map_working_image
from src.gui.layout_manager import normalize_layout
from src.gui.telemetry_manager import TelemetryDataManager
from src.moving_map import MovingMapRenderer
from src.telemetry_extract import (
    ensure_records_list, load_json_with_fallback,
    extract_speed_samples, extract_altitude_samples, extract_track_samples,
    extract_iso_samples, extract_exposure_samples, extract_temperature_samples,
    smooth_speed_samples, interpolate_value, get_rotation_from_metadata,
    get_container_rotation, find_metadata_json, extract_gps_track,
    smooth_speed_values, extract_accelerometer_samples, extract_gyroscope_samples,
)

out_dir = root / "Raporty" / "etap8u_b_artifacts"
out_dir.mkdir(parents=True, exist_ok=True)

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

renderer = MovingMapRenderer(gps_track, zoom=18, style="light_all")
dur = gps_track[-1][0].timestamp() - gps_track[0][0].timestamp()

print("Comparing 100 representative frames between REFERENCE (692 Lanczos) and DIRECT (691 Native)...")
maes = []
max_diffs = []
psnrs = []
diff_ratios = []

num_frames = 100
for i in range(num_frames):
    pos = i / float(num_frames - 1)
    ts = pos * dur
    
    # Reference: 692 -> resize Lanczos to 691
    img_692 = renderer.render(ts, 692, 692)
    img_ref = img_692.resize((691, 691), Image.Resampling.LANCZOS)
    
    # Direct: 691 Native
    img_dir = renderer.render(ts, 691, 691)
    
    arr_ref = np.array(img_ref, dtype=np.float32)
    arr_dir = np.array(img_dir, dtype=np.float32)
    
    diff = np.abs(arr_ref - arr_dir)
    mae = float(np.mean(diff))
    max_d = int(np.max(diff))
    mse = float(np.mean(diff ** 2))
    psnr = 10.0 * math.log10(255.0 ** 2 / mse) if mse > 0 else 99.0
    diff_px = float(np.mean(np.any(diff > 1.0, axis=2)))
    
    maes.append(mae)
    max_diffs.append(max_d)
    psnrs.append(psnr)
    diff_ratios.append(diff_px)
    
    if i == 50: # Mid frame for visual crops
        # 1. Full images
        img_ref.save(out_dir / "crop_reference_full.png")
        img_dir.save(out_dir / "crop_direct_full.png")
        diff_full = np.clip(np.abs(arr_ref.astype(np.int16) - arr_dir.astype(np.int16)) * 10, 0, 255).astype(np.uint8)
        Image.fromarray(diff_full).save(out_dir / "crop_diff_full_x10.png")
        
        # 2. Center Marker Crop (100x100 around center)
        cx, cy = 691 // 2, 691 // 2
        box = (cx - 50, cy - 50, cx + 50, cy + 50)
        img_ref.crop(box).save(out_dir / "crop_marker_ref.png")
        img_dir.crop(box).save(out_dir / "crop_marker_dir.png")
        Image.fromarray(diff_full).crop(box).save(out_dir / "crop_marker_diff_x10.png")
        
        # 3. Corner Crop (top-left 100x100)
        box_c = (0, 0, 100, 100)
        img_ref.crop(box_c).save(out_dir / "crop_corner_ref.png")
        img_dir.crop(box_c).save(out_dir / "crop_corner_dir.png")
        Image.fromarray(diff_full).crop(box_c).save(out_dir / "crop_corner_diff_x10.png")

print(f"\n=== 100-FRAME QUALITY METRICS (REFERENCE vs DIRECT) ===")
print(f"MAE:            {np.mean(maes):.4f} / 255 (median={np.median(maes):.4f}, min={np.min(maes):.4f}, max={np.max(maes):.4f})")
print(f"PSNR:           {np.mean(psnrs):.2f} dB (median={np.median(psnrs):.2f}, min={np.min(psnrs):.2f}, max={np.max(psnrs):.2f})")
print(f"MAX Pixel Diff: {np.max(max_diffs)} / 255 (median max={np.median(max_diffs):.0f})")
print(f"Diff Pixels:    {np.mean(diff_ratios)*100:.2f}% (median={np.median(diff_ratios)*100:.2f}%)")
print(f"Crops saved to: {out_dir}")
