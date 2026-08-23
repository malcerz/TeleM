import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import json
from src.indicators.compositor import compose_overlay
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

def test_config(name, ind_dict):
    l = json.loads(json.dumps(v10_layout))
    l["indicators"] = ind_dict
    
    # Range cache like in PreviewMixin
    max_dist = None
    indic = l["indicators"]
    dist_src = indic.get("dist_visual", {}).get("source", "gpmf")
    if dist_src == "fit":
        trk_for_range = telemetry.fit_data.get("track", [])
    else:
        trk_for_range = telemetry.track_samples
    if trk_for_range:
        max_dist = trk_for_range[-1][1]
        
    prep_cache = {"max_distance_m": max_dist}
    
    extra_keys = [k[4:-5] for k in indic.keys() if k.startswith("fit_") and k.endswith("_text")]
    
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
        
        # Check all indicators in ind_dict
        for k in ind_dict.keys():
            bb = bboxes.get(k)
            if bb:
                ox, oy, ow, oh = bb
                crop = overlay.crop((ox, oy, ox + ow, oy + oh))
                arr = np.array(crop)
                # Find white marker border or yellow/blue marker center
                # White marker border is #FFFFFF (255, 255, 255)
                # Yellow marker center is #FFD42A (255, 212, 42)
                mask_y = (arr[:, :, 0] == 255) & (arr[:, :, 1] == 212) & (arr[:, :, 2] == 42) & (arr[:, :, 3] > 200)
                ys, xs = np.where(mask_y)
                cx = float(np.mean(xs)) if len(xs) > 0 else None
                print(f"[{name}] ts={ts:5.1f}s | key={k} | bbox={bb} | marker_local_x={cx}")

print("\n--- TEST 1: dist_visual (source='gpmf', min=0, max=10) ---")
test_config("dist_visual_gpmf", {
    "dist_visual": {
        "enabled": True, "label": "DISTANCE", "x": 50.0, "y": 74.0, "rotation": 0,
        "form": "bar", "bar_style": "ruler", "font_size": 1.2, "size": 28.0, "thickness": 1,
        "min_val": 0.0, "max_val": 10.0, "ticks": 5, "show_value": True, "source": "gpmf", "unit": "km"
    }
})

print("\n--- TEST 2: dist_visual (source='fit', min=0, max=25) ---")
test_config("dist_visual_fit", {
    "dist_visual": {
        "enabled": True, "label": "DISTANCE", "x": 50.0, "y": 74.0, "rotation": 0,
        "form": "bar", "bar_style": "ruler", "font_size": 1.2, "size": 28.0, "thickness": 1,
        "min_val": 0.0, "max_val": 25.0, "ticks": 5, "show_value": True, "source": "fit", "unit": "km"
    }
})

print("\n--- TEST 3: dist_text (source='fit', form='bar', min=0, max=25) ---")
test_config("dist_text_fit", {
    "dist_text": {
        "enabled": True, "label": "DISTANCE", "x": 50.0, "y": 74.0, "rotation": 0,
        "form": "bar", "bar_style": "ruler", "font_size": 1.2, "size": 28.0, "thickness": 1,
        "min_val": 0.0, "max_val": 25.0, "ticks": 5, "show_value": True, "source": "fit", "unit": "km"
    }
})

print("\n--- TEST 4: fit_distance_text (source='fit', form='bar', min=0, max=25) ---")
test_config("fit_distance_text", {
    "fit_distance_text": {
        "enabled": True, "label": "DISTANCE", "x": 50.0, "y": 74.0, "rotation": 0,
        "form": "bar", "bar_style": "ruler", "font_size": 1.2, "size": 28.0, "thickness": 1,
        "min_val": 0.0, "max_val": 25.0, "ticks": 5, "show_value": True, "source": "fit", "unit": "km"
    }
})
