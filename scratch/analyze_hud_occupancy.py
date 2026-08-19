"""
Deep HUD Occupancy and Alpha Histogram Analysis across 1131 frames.
"""
import os
import sys
import numpy as np
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
from src.gui.layout_manager import normalize_layout
from src.indicators.compositor import compose_overlay
from src.indicators.moving_map import render_map_working_image

v_1131 = root / "Video" / "GX020079.mp4"
fit_1131 = root / "Video" / "Morning_Ride.fit"

def run_occupancy_analysis():
    print("Initializing telemetry for 1131 frames...", flush=True)
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
    records = ensure_records_list(load_json_with_fallback(v_1131.with_suffix(".json")))
    tm.load_gpmf_records(records)
    tm.load_fit(str(fit_1131))
    
    W, H = 3840, 2160
    TOTAL_PIXELS = W * H
    layout = normalize_layout(root / "def_layout.json", W, H)
    gps_track = tm.get_gps_track_for_source("fit")
    
    # Analyze 50 sampled frames across the 1131 material (every ~23 frames) to get precise distribution
    frame_indices = list(range(0, 1131, 23))
    print(f"Sampling {len(frame_indices)} representative frames across 1131 material...", flush=True)
    
    alpha_zero_pcts = []
    alpha_semi_pcts = []
    alpha_full_pcts = []
    
    tile16_active_pcts = []
    tile32_active_pcts = []
    tile64_active_pcts = []
    
    bbox_union_pcts = []
    
    for f_idx in frame_indices:
        t_sec = f_idx / 29.97
        telemetry_dict = {
            "speed": tm.get_speed(t_sec),
            "altitude": tm.get_altitude(t_sec),
            "heart_rate": tm.get_heart_rate(t_sec),
            "cadence": tm.get_cadence(t_sec),
            "power": tm.get_power(t_sec),
            "temperature": tm.get_temperature(t_sec),
            "track": tm.get_track(t_sec),
            "lat": tm.get_lat(t_sec),
            "lon": tm.get_lon(t_sec),
        }
        
        # 1. Base Pillow HUD (BELOW + Text/Above)
        hud_img = compose_overlay(
            W, H, layout, telemetry_dict,
            time_offset=t_sec,
            gps_track=gps_track,
            current_position=(t_sec / (1131 / 29.97)),
            font_path="assets/Roboto-Bold.ttf",
            indicators_filter=None,
        )
        
        # 2. Add Map contribution if GPU-resident map is blended to HUD
        map_img, map_bbox = render_map_working_image(
            W, H, layout, "track_map", gps_track, current_position=(t_sec / (1131 / 29.97))
        )
        if map_img is not None and map_bbox is not None:
            hud_img.paste(map_img, (map_bbox[0], map_bbox[1]), map_img)
            
        # Convert to numpy array to measure alpha
        arr = np.array(hud_img)
        alpha = arr[:, :, 3]
        
        cnt_zero = np.count_nonzero(alpha == 0)
        cnt_semi = np.count_nonzero((alpha > 0) & (alpha < 255))
        cnt_full = np.count_nonzero(alpha == 255)
        
        alpha_zero_pcts.append(cnt_zero / TOTAL_PIXELS * 100.0)
        alpha_semi_pcts.append(cnt_semi / TOTAL_PIXELS * 100.0)
        alpha_full_pcts.append(cnt_full / TOTAL_PIXELS * 100.0)
        
        # Tile 16x16
        # Shape: (135, 16, 240, 16)
        alpha_16 = alpha.reshape(H // 16, 16, W // 16, 16).swapaxes(1, 2)
        tiles16_active = np.count_nonzero(np.any(alpha_16 > 0, axis=(2, 3)))
        tile16_active_pcts.append(tiles16_active / (135 * 240) * 100.0)
        
        # Tile 32x32 (H padded or 2160//32 = 67.5 -> handle 67 full 32x32 + 1 partial 16x32)
        # Pad to 2176 x 3840 (68 x 120 tiles)
        pad_h = 2176 - H
        alpha_padded = np.pad(alpha, ((0, pad_h), (0, 0)), mode='constant')
        alpha_32 = alpha_padded.reshape(68, 32, 120, 32).swapaxes(1, 2)
        tiles32_active = np.count_nonzero(np.any(alpha_32 > 0, axis=(2, 3)))
        tile32_active_pcts.append(tiles32_active / (68 * 120) * 100.0)
        
        # Tile 64x64
        pad_h64 = 2176 - H # 34 x 60 tiles
        alpha_64 = alpha_padded.reshape(34, 64, 60, 64).swapaxes(1, 2)
        tiles64_active = np.count_nonzero(np.any(alpha_64 > 0, axis=(2, 3)))
        tile64_active_pcts.append(tiles64_active / (34 * 60) * 100.0)
        
        # BBox Union
        y_indices, x_indices = np.where(alpha > 0)
        if len(x_indices) > 0:
            min_x, max_x = x_indices.min(), x_indices.max()
            min_y, max_y = y_indices.min(), y_indices.max()
            bbox_union_area = (max_x - min_x + 1) * (max_y - min_y + 1)
            bbox_union_pcts.append(bbox_union_area / TOTAL_PIXELS * 100.0)
        else:
            bbox_union_pcts.append(0.0)
            
    print("\n=======================================================")
    print("=== HUD OCCUPANCY & ALPHA HISTOGRAM RESULTS (4K) ===")
    print("=======================================================")
    print(f"Total Output Pixels:           {TOTAL_PIXELS:,} (3840 x 2160)")
    print(f"Alpha == 0 (Fully Transparent): {np.mean(alpha_zero_pcts):.2f}% (approx {int(np.mean(alpha_zero_pcts)/100*TOTAL_PIXELS):,} pixels)")
    print(f"0 < Alpha < 255 (Semi-Trans):   {np.mean(alpha_semi_pcts):.2f}% (approx {int(np.mean(alpha_semi_pcts)/100*TOTAL_PIXELS):,} pixels)")
    print(f"Alpha == 255 (Fully Opaque):    {np.mean(alpha_full_pcts):.2f}% (approx {int(np.mean(alpha_full_pcts)/100*TOTAL_PIXELS):,} pixels)")
    print(f"Total Non-Zero HUD Pixels:      {100.0 - np.mean(alpha_zero_pcts):.2f}% (approx {int((100.0-np.mean(alpha_zero_pcts))/100*TOTAL_PIXELS):,} pixels)")
    print("-------------------------------------------------------")
    print(f"16x16 Active Tiles:             {np.mean(tile16_active_pcts):.2f}% ({int(np.mean(tile16_active_pcts)/100*32400):,} / 32,400 tiles)")
    print(f"32x32 Active Tiles:             {np.mean(tile32_active_pcts):.2f}% ({int(np.mean(tile32_active_pcts)/100*8160):,} / 8,160 tiles)")
    print(f"64x64 Active Tiles:             {np.mean(tile64_active_pcts):.2f}% ({int(np.mean(tile64_active_pcts)/100*2040):,} / 2,040 tiles)")
    print(f"Bounding-Box Union Area:        {np.mean(bbox_union_pcts):.2f}% ({int(np.mean(bbox_union_pcts)/100*TOTAL_PIXELS):,} pixels)")
    print("=======================================================")

if __name__ == "__main__":
    run_occupancy_analysis()
