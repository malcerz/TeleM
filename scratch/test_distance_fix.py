import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import json
from src.indicators.compositor import compose_overlay
from src.indicators.dispatcher import render_value_indicator
from src.gui.telemetry_manager import TelemetryDataManager
from src.indicators.frame_data import prepare_overlay_frame_data
from src.telemetry_extract import *
from datetime import timedelta
import numpy as np

root = Path(__file__).resolve().parents[1]
video_path = root / "Video" / "GX010115.MP4"
json_path = root / "Video" / "GX010115.json"
fit_path = root / "Video" / "Jazda_na_rowerze_w_porze_lunchu.fit"
layout_path = root / "presets" / "cycling_dashboard_v10.json"

with open(layout_path, "r", encoding="utf-8") as f:
    v10_layout = json.load(f)

with open(json_path, "r", encoding="utf-8") as f:
    meta = json.load(f)
records = ensure_records_list(meta)

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

telemetry.load_gpmf_records(records)
telemetry.load_gps_track(records)
telemetry.load_fit(video_path, telemetry.start_dt_utc, manual_path=fit_path)

dt = telemetry.start_dt_utc

# Test function for any layout configuration
def run_trace(name, ind_key, ind_cfg):
    l = json.loads(json.dumps(v10_layout))
    l["indicators"] = {ind_key: ind_cfg}
    
    # Range cache resolution
    dist_src = ind_cfg.get("source", "gpmf")
    if dist_src == "fit":
        trk = telemetry.fit_data.get("track", [])
    elif dist_src == "gpx":
        trk = telemetry.gpx_track_samples
    else:
        trk = telemetry.track_samples
    max_dist = trk[-1][1] if trk else None
    
    prep_cache = {"max_distance_m": max_dist}
    extra_keys = ["distance"] if ind_key.startswith("fit_") else []
    
    print(f"\n==================== {name} (source={dist_src}, key={ind_key}) ====================")
    print(f"max_distance_m: {max_dist} m ({max_dist/1000.0:.3f} km)")
    
    for ts in [0.0, 30.0, 60.0, 90.0, 120.0]:
        target_dt = dt + timedelta(seconds=ts)
        kw = prepare_overlay_frame_data(
            layout=l, target_dt=target_dt, tz_offset_hours=2.0, start_dt_utc=dt,
            speed_samples=telemetry.speed_samples, track_samples=telemetry.track_samples,
            alt_samples=telemetry.alt_samples, iso_samples=telemetry.iso_samples,
            exposure_samples=telemetry.exposure_samples, temperature_samples=telemetry.temperature_samples,
            fit_data=telemetry.fit_data, gps_track=telemetry.get_gps_track_for_source("fit"),
            extra_field_keys=extra_keys,
            resolve_cache_value=lambda k, s, d, ind=None: telemetry.resolve_value(k, d, source=s, indicator_key=ind),
            _range_cache=prep_cache,
        )
        
        bboxes = {}
        overlay = compose_overlay(1280, 720, l, "", _bboxes=bboxes, **kw)
        bb = bboxes.get(ind_key)
        
        # Find marker pixel on crop
        ox, oy, ow, oh = bb
        crop = overlay.crop((ox, oy, ox + ow, oy + oh))
        arr = np.array(crop)
        
        # Marker border color in v10 is white #FFFFFF or yellow #FFD42A
        # Find yellow marker center
        mask_y = (arr[:, :, 0] == 255) & (arr[:, :, 1] == 212) & (arr[:, :, 2] == 42) & (arr[:, :, 3] > 200)
        ys_y, xs_y = np.where(mask_y)
        cx = float(np.mean(xs_y)) if len(xs_y) > 0 else None
        
        # Also check white marker border if color is different
        if cx is None:
            mask_w = (arr[:, :, 0] == 255) & (arr[:, :, 1] == 255) & (arr[:, :, 2] == 255) & (arr[:, :, 3] > 200)
            # Find in track row
            ys_w, xs_w = np.where(mask_w)
            cx = float(np.mean(xs_w)) if len(xs_w) > 0 else None
            
        print(f"ts={ts:5.1f}s | dist_m={kw.get('distance_m')} | marker_x={cx} | bbox={bb}")

# Test 1: dist_visual (gpmf)
run_trace("dist_visual_gpmf", "dist_visual", v10_layout["indicators"]["dist_visual"])

# Test 2: dist_visual (fit)
cfg_fit = v10_layout["indicators"]["dist_visual"].copy()
cfg_fit["source"] = "fit"
run_trace("dist_visual_fit", "dist_visual", cfg_fit)
