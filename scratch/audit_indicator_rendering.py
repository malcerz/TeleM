"""Trace indicator rendering and check map geometry, battery None handling, and above_bbox_crop."""
import json
import math
import sys
from pathlib import Path
from PIL import Image

root = Path("c:/_DEV/TeleM")
sys.path.insert(0, str(root))
sys.path.insert(0, str(root / "src"))

from src.gui.telemetry_manager import TelemetryDataManager
from src.telemetry_extract import (
    ensure_records_list, extract_altitude_samples, extract_exposure_samples,
    extract_iso_samples, extract_speed_samples, extract_temperature_samples,
    extract_track_samples, interpolate_value, load_json_with_fallback,
    smooth_speed_samples
)
from src.indicators.compositor import compose_overlay
from src.ffmpeg.amd_native_exporter import _ordered_map_layout_parts
def s(val, base): return int(round(val * base / 100.0))

def run_trace():
    fit_path = root / "Video" / "Popoludniowa_jazda_na_rowerze_solar_battery.fit"
    json_path = root / "Video" / "GX030120.json"
    records = ensure_records_list(load_json_with_fallback(json_path))
    tm = TelemetryDataManager(
        extract_speed_samples, extract_altitude_samples, extract_track_samples,
        extract_iso_samples, extract_exposure_samples, extract_temperature_samples,
        smooth_speed_samples, interpolate_value
    )
    tm.load_gpmf_records(records)
    tm.load_fit(fit_path)
    tm.start_dt_utc = tm.speed_samples[0][0]

    layout = json.load(open(root / "def_layout.json", encoding="utf-8"))
    
    speed = smooth_speed_samples(tm.speed_samples, "moving_average", 5)
    alt = smooth_speed_samples(tm.alt_samples, "moving_average", 5)
    track = tm.track_samples

    print("\n=== TRACING RENDER_OVERLAY / COMPOSE_OVERLAY FOR FRAME 30 ===")
    frame_idx = 30
    pts_s = frame_idx * (1001.0 / 30000.0)
    curr_dt = tm.start_dt_utc + (tm.speed_samples[-1][0] - tm.speed_samples[0][0]) * (pts_s / 180.0) # approximate dt
    
    # Check field samples passed to compositor
    field_samples = {"speed_samples": speed, "track_samples": track, "alt_samples": alt}
    if tm.fit_data:
        for k, v in tm.fit_data.items():
            field_samples[f"{k}_samples"] = v

    print(f"Available field_samples keys in compositor: {sorted(field_samples.keys())}")
    
    # 1. Render full CPU compose_overlay (which includes map in CPU mode)
    img_full, bboxes_full = compose_overlay(
        3840, 2160, layout,
        current_time=curr_dt,
        font_path="arial.ttf",
        speed_samples=speed,
        track_samples=track,
        alt_samples=alt,
        field_samples=field_samples,
        fit_data=tm.fit_data,
        gps_track=tm.get_gps_track_for_source("fit"),
        target_dt=curr_dt,
        current_position=pts_s / 180.0,
    )
    print(f"Full CPU compose bboxes count: {len(bboxes_full)}")
    for k, bb in bboxes_full.items():
        print(f"  Widget '{k}': bbox={bb}")

    # 2. Render ordered CPU_BELOW_MAP and CPU_ABOVE_MAP
    below_keys, map_key, above_keys = _ordered_map_layout_parts(layout)
    print(f"\nOrdered layout parts: BELOW={below_keys}, MAP={map_key}, ABOVE={above_keys}")
    
    img_above, bboxes_above = compose_overlay(
        3840, 2160, layout,
        current_time=curr_dt,
        font_path="arial.ttf",
        speed_samples=speed,
        track_samples=track,
        alt_samples=alt,
        field_samples=field_samples,
        fit_data=tm.fit_data,
        gps_track=tm.get_gps_track_for_source("fit"),
        target_dt=curr_dt,
        current_position=pts_s / 180.0,
        active_keys=set(above_keys),
    )
    print(f"ABOVE bboxes count: {len(bboxes_above)}")
    for k, bb in bboxes_above.items():
        print(f"  ABOVE Widget '{k}': bbox={bb}")

    # Union candidate bbox calculation
    if bboxes_above:
        min_x = min(bb[0] for bb in bboxes_above.values())
        min_y = min(bb[1] for bb in bboxes_above.values())
        max_x = max(bb[0] + bb[2] for bb in bboxes_above.values())
        max_y = max(bb[1] + bb[3] for bb in bboxes_above.values())
        cand_w = max_x - min_x
        cand_h = max_y - min_y
        cand_pixels = cand_w * cand_h
        pct_screen = (cand_pixels / (3840 * 2160)) * 100.0
        print(f"\nUnion Candidate Bbox for ABOVE: [{min_x}, {min_y}, {cand_w}, {cand_h}]")
        print(f"Candidate Surface: {cand_pixels:,} pixels ({pct_screen:.2f}% of 4K screen)")

if __name__ == "__main__":
    run_trace()
