import json
import time
import sys
from pathlib import Path
import numpy as np

root = Path("c:/_DEV/TeleM")
sys.path.insert(0, str(root))
sys.path.insert(0, str(root / "src"))

def audit_fit_values():
    print("=== 1. AUDITING FIT FILE: Popoludniowa_jazda_na_rowerze_solar_battery.fit ===")
    from src.gui.telemetry_manager import TelemetryDataManager
    from src.telemetry_extract import (
        ensure_records_list, extract_altitude_samples, extract_exposure_samples,
        extract_iso_samples, extract_speed_samples, extract_temperature_samples,
        extract_track_samples, interpolate_value, load_json_with_fallback,
        smooth_speed_samples
    )
    from telemetry_fit import parse_fit

    fit_path = root / "Video" / "Popoludniowa_jazda_na_rowerze_solar_battery.fit"
    raw_records = parse_fit(fit_path)
    print(f"FIT raw records count: {len(raw_records)}")
    if raw_records:
        print(f"Sample raw record 0 keys: {list(raw_records[0].keys())}")
        print(f"Sample raw record 0: {raw_records[0]}")

    # Check GPMF json
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

    print(f"\nDiscovered tm.fit_data fields: {list(tm.fit_data.keys())}")
    for k, pts in tm.fit_data.items():
        vals = [p[1] for p in pts if p[1] is not None]
        print(f"  FIT field '{k}': {len(pts)} pts ({len(vals)} non-None), min={min(vals) if vals else 'N/A'}, max={max(vals) if vals else 'N/A'}, sample={pts[:3]}")

    print("\n=== 2. TELEMETRY MANAGER INTERPOLATED VALUES CHECK ===")
    for target_idx in [0, 30, 225, 450, 1000, 2500, 5000]:
        target_dt = tm.get_time_for_frame(target_idx, 29.97002997)
        frame_dict = tm.get_frame_data_at_time(target_dt)
        print(f"Frame {target_idx:4d} (dt={target_dt}):")
        for k in ["battery", "battery_pct", "battery_pct_x100", "solar_pct", "heart_rate", "cadence", "temperature", "curVpower"]:
            v = frame_dict.get(k)
            print(f"    {k:18s} = {v} (type={type(v).__name__})")

def audit_above_bbox_crop_geometry():
    print("\n=== 3. AUDITING ABOVE_BBOX_CROP GEOMETRY ===")
    from src.indicators.compositor import _ordered_map_layout_parts
    from src.indicators.scale import s
    
    layout = json.load(open(root / "def_layout.json", encoding="utf-8"))
    below_keys, map_key, above_keys = _ordered_map_layout_parts(layout)
    print(f"Below keys: {below_keys}")
    print(f"Map key: {map_key}")
    print(f"Above keys: {above_keys}")
    
    indicators = layout.get("indicators", {})
    canvas_w, canvas_h = 3840, 2160
    
    for k in above_keys:
        cfg = indicators[k]
        x_pct = cfg.get("x", 50.0)
        y_pct = cfg.get("y", 8.0)
        size_val = cfg.get("size", 2.5)
        cx = s(x_pct, canvas_w)
        cy = s(y_pct, canvas_h)
        print(f"  Above indicator '{k}': x_pct={x_pct}%, y_pct={y_pct}% -> pos=({cx:.1f}, {cy:.1f}), size={size_val}, label='{cfg.get('label')}'")

if __name__ == "__main__":
    audit_fit_values()
    audit_above_bbox_crop_geometry()
