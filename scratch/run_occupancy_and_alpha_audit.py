"""
ETAP 8V-A: Full HUD Occupancy and Alpha Histogram Deep Audit across 1131 frames.
"""
import os
import sys
import json
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
from src.telemetry_precompute import build_telemetry_cache

v_1131 = root / "Video" / "GX020079.mp4"
fit_1131 = root / "Video" / "Morning_Ride.fit"

def audit_occupancy():
    print("Loading telemetry...", flush=True)
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
    
    cache = build_telemetry_cache(
        layout=layout,
        base_dt=tm.start_dt_utc,
        tz_offset_hours=2.0,
        start_dt_utc=tm.start_dt_utc,
        speed_samples=tm.speed_samples or [],
        track_samples=tm.track_samples or [],
        alt_samples=tm.alt_samples or [],
        iso_samples=tm.iso_samples,
        exposure_samples=tm.exposure_samples,
        temperature_samples=tm.temperature_samples,
        fit_data=tm.fit_data,
        gps_track=gps_track,
        total_frames=1131,
        target_fps=29.97,
    )
    
    print(f"Precomputed cache built for {len(cache.records)} frames.", flush=True)
    
    # Sample 50 frames across 1131 material
    sample_indices = list(range(0, 1131, 23))
    
    alpha_0_list = []
    alpha_semi_list = []
    alpha_255_list = []
    
    tile16_active_list = []
    tile32_active_list = []
    tile64_active_list = []
    
    bbox_union_area_list = []
    
    # Save a sample mask image
    sample_mask_saved = False
    
    for f_idx in sample_indices:
        t_sec = f_idx / 29.97
        kwargs = cache.lookup(f_idx)
        
        # 1. Compose full overlay (including charts, gauge, texts, map)
        hud_img = compose_overlay(
            canvas_w=W,
            canvas_h=H,
            layout=layout,
            font_path="assets/Roboto-Bold.ttf",
            reuse_canvas=False,
            **kwargs,
        )
        
        # Render map and paste to HUD (since GPU-resident map is part of the final composite)
        map_img, map_dst = render_map_working_image(
            W, H, layout, "track_map", gps_track, target_dt=kwargs.get("curr_dt"),
            current_position=kwargs.get("current_position")
        )
        if map_img is not None and map_dst is not None:
            hud_img.paste(map_img, (map_dst[0], map_dst[1]), map_img)
            
        arr = np.array(hud_img)
        alpha = arr[:, :, 3]
        
        c0 = np.count_nonzero(alpha == 0)
        c_semi = np.count_nonzero((alpha > 0) & (alpha < 255))
        c255 = np.count_nonzero(alpha == 255)
        
        alpha_0_list.append(c0 / TOTAL_PIXELS * 100.0)
        alpha_semi_list.append(c_semi / TOTAL_PIXELS * 100.0)
        alpha_255_list.append(c255 / TOTAL_PIXELS * 100.0)
        
        # 16x16 tiles (240 x 135 = 32400)
        alpha_16 = alpha.reshape(135, 16, 240, 16).swapaxes(1, 2)
        t16_act = np.count_nonzero(np.any(alpha_16 > 0, axis=(2, 3)))
        tile16_active_list.append(t16_act / 32400.0 * 100.0)
        
        # 32x32 tiles (120 x 68 = 8160)
        pad_h = 2176 - H
        alpha_pad = np.pad(alpha, ((0, pad_h), (0, 0)), mode='constant')
        alpha_32 = alpha_pad.reshape(68, 32, 120, 32).swapaxes(1, 2)
        t32_act = np.count_nonzero(np.any(alpha_32 > 0, axis=(2, 3)))
        tile32_active_list.append(t32_act / 8160.0 * 100.0)
        
        # 64x64 tiles (60 x 34 = 2040)
        alpha_64 = alpha_pad.reshape(34, 64, 60, 64).swapaxes(1, 2)
        t64_act = np.count_nonzero(np.any(alpha_64 > 0, axis=(2, 3)))
        tile64_active_list.append(t64_act / 2040.0 * 100.0)
        
        # Bounding box union
        ys, xs = np.where(alpha > 0)
        if len(xs) > 0:
            bw = xs.max() - xs.min() + 1
            bh = ys.max() - ys.min() + 1
            bbox_union_area_list.append((bw * bh) / TOTAL_PIXELS * 100.0)
            
        if not sample_mask_saved and f_idx == 0:
            # Save 16x16 tile mask visualization
            mask_16_img = Image.fromarray((np.any(alpha_16 > 0, axis=(2, 3)) * 255).astype(np.uint8))
            mask_16_img.resize((W, H), Image.NEAREST).save("Raporty/etap8v_a_artifacts/tile_mask_16x16_frame0.png")
            sample_mask_saved = True
            
    out_dict = {
        "total_pixels": TOTAL_PIXELS,
        "alpha_0_pct_mean": float(np.mean(alpha_0_list)),
        "alpha_semi_pct_mean": float(np.mean(alpha_semi_list)),
        "alpha_255_pct_mean": float(np.mean(alpha_255_list)),
        "hud_active_pixels_pct_mean": float(100.0 - np.mean(alpha_0_list)),
        "tile16_active_pct_mean": float(np.mean(tile16_active_list)),
        "tile16_active_count_mean": float(np.mean(tile16_active_list) / 100.0 * 32400),
        "tile32_active_pct_mean": float(np.mean(tile32_active_list)),
        "tile32_active_count_mean": float(np.mean(tile32_active_list) / 100.0 * 8160),
        "tile64_active_pct_mean": float(np.mean(tile64_active_list)),
        "tile64_active_count_mean": float(np.mean(tile64_active_list) / 100.0 * 2040),
        "bbox_union_pct_mean": float(np.mean(bbox_union_area_list)),
    }
    
    print("\n=======================================================")
    print("=== FINAL HUD OCCUPANCY AUDIT (4K 3840x2160) ===")
    print("=======================================================")
    print(f"Alpha == 0 (Fully Transparent):   {out_dict['alpha_0_pct_mean']:.2f}% ({int(out_dict['alpha_0_pct_mean']/100*TOTAL_PIXELS):,} px)")
    print(f"0 < Alpha < 255 (Antialiased):     {out_dict['alpha_semi_pct_mean']:.2f}% ({int(out_dict['alpha_semi_pct_mean']/100*TOTAL_PIXELS):,} px)")
    print(f"Alpha == 255 (Fully Opaque):      {out_dict['alpha_255_pct_mean']:.2f}% ({int(out_dict['alpha_255_pct_mean']/100*TOTAL_PIXELS):,} px)")
    print(f"Total Non-Zero HUD Pixels:        {out_dict['hud_active_pixels_pct_mean']:.2f}% ({int(out_dict['hud_active_pixels_pct_mean']/100*TOTAL_PIXELS):,} px)")
    print("-------------------------------------------------------")
    print(f"16x16 Active Tiles:               {out_dict['tile16_active_pct_mean']:.2f}% ({out_dict['tile16_active_count_mean']:.0f} / 32,400 tiles)")
    print(f"32x32 Active Tiles:               {out_dict['tile32_active_pct_mean']:.2f}% ({out_dict['tile32_active_count_mean']:.0f} / 8,160 tiles)")
    print(f"64x64 Active Tiles:               {out_dict['tile64_active_pct_mean']:.2f}% ({out_dict['tile64_active_count_mean']:.0f} / 2,040 tiles)")
    print(f"Bounding-Box Union Area:          {out_dict['bbox_union_pct_mean']:.2f}% ({int(out_dict['bbox_union_pct_mean']/100*TOTAL_PIXELS):,} px)")
    print("=======================================================")
    
    with open("Raporty/etap8v_a_artifacts/occupancy_results.json", "w") as f:
        json.dump(out_dict, f, indent=2)

if __name__ == "__main__":
    os.makedirs("Raporty/etap8v_a_artifacts", exist_ok=True)
    audit_occupancy()
