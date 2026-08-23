import sys
import json
import time
from pathlib import Path
from collections import defaultdict
import statistics

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.gui.telemetry_manager import TelemetryDataManager
from src.indicators.frame_data import prepare_overlay_frame_data
import src.indicators.compositor as compositor
from src.telemetry_extract import (
    extract_speed_samples, extract_altitude_samples, extract_track_samples,
    extract_iso_samples, extract_exposure_samples, extract_temperature_samples,
    ensure_records_list, extract_gps_track,
    smooth_speed_samples, interpolate_value, get_rotation_from_metadata,
    get_container_rotation, find_metadata_json, load_json_with_fallback,
    smooth_speed_values, extract_accelerometer_samples, extract_gyroscope_samples,
)

root = Path(__file__).resolve().parents[1]
video_path = root / "Video" / "GX010115.MP4"
json_path = root / "Video" / "GX010115.json"
fit_path = root / "Video" / "Jazda_na_rowerze_w_porze_lunchu.fit"
layout_path = root / "presets" / "cycling_dashboard_v10.json"

with open(layout_path, "r", encoding="utf-8") as f:
    layout = json.load(f)

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

with open(json_path, "r", encoding="utf-8") as f:
    meta = json.load(f)
records = ensure_records_list(meta)
telemetry.load_gpmf_records(records)
telemetry.load_gps_track(records)
telemetry.load_fit(video_path, telemetry.start_dt_utc, manual_path=fit_path)

timings = defaultdict(lambda: defaultdict(list))
orig_render = compositor.render_value_indicator
orig_paste = compositor.rotated_paste

def hooked_render(*args, **kwargs):
    key = args[4] if len(args) > 4 else kwargs.get("key")
    t0 = time.perf_counter()
    res = orig_render(*args, **kwargs)
    t1 = time.perf_counter()
    timings[key]["render"].append((t1 - t0) * 1000.0)
    return res

def hooked_paste(target, source, cx, cy, rotation, *args, **kwargs):
    cache_key = kwargs.get("cache_key", "unknown")
    t0 = time.perf_counter()
    res = orig_paste(target, source, cx, cy, rotation, *args, **kwargs)
    t1 = time.perf_counter()
    timings[cache_key]["paste"].append((t1 - t0) * 1000.0)
    return res

compositor.render_value_indicator = hooked_render
compositor.rotated_paste = hooked_paste

from datetime import timedelta
start_dt = telemetry.start_dt_utc

# Warmup 10 frames
for i in range(10):
    dt = start_dt + timedelta(seconds=i / 60.0)
    kwargs = prepare_overlay_frame_data(
        target_dt=dt,
        start_dt_utc=start_dt,
        tz_offset_hours=2.0,
        layout=layout,
        speed_samples=telemetry.speed_samples,
        track_samples=telemetry.track_samples,
        alt_samples=telemetry.alt_samples,
        iso_samples=telemetry.iso_samples,
        exposure_samples=telemetry.exposure_samples,
        temperature_samples=telemetry.temperature_samples,
        fit_data=telemetry.fit_data,
        gps_track=telemetry.get_gps_track_for_source("fit"),
        resolve_cache_value=lambda k, src, d, ind=None: telemetry.resolve_value(k, d, source=src),
    )
    compositor.compose_overlay(1280, 720, layout, "", reuse_canvas="above", **kwargs)

timings.clear()

# Measure steady-state frames 11-120
for i in range(10, 120):
    dt = start_dt + timedelta(seconds=i / 60.0)
    kwargs = prepare_overlay_frame_data(
        target_dt=dt,
        start_dt_utc=start_dt,
        tz_offset_hours=2.0,
        layout=layout,
        speed_samples=telemetry.speed_samples,
        track_samples=telemetry.track_samples,
        alt_samples=telemetry.alt_samples,
        iso_samples=telemetry.iso_samples,
        exposure_samples=telemetry.exposure_samples,
        temperature_samples=telemetry.temperature_samples,
        fit_data=telemetry.fit_data,
        gps_track=telemetry.get_gps_track_for_source("fit"),
        resolve_cache_value=lambda k, src, d, ind=None: telemetry.resolve_value(k, d, source=src),
    )
    compositor.compose_overlay(1280, 720, layout, "", reuse_canvas="above", **kwargs)

print("\n" + "="*85)
print("PRODUCTION BASELINE (Frames 11-120 Steady State)")
print("="*85)

for k in ["fit_heart_rate_text", "fit_cadence_text"]:
    r_list = timings[k]["render"]
    p_list = timings[k]["paste"]
    tot_list = [r + p for r, p in zip(r_list, p_list)]
    print(f"\n### {k} ###")
    print(f"  Render:  mean={statistics.fmean(r_list):.3f} ms | median={statistics.median(r_list):.3f} ms")
    print(f"  Paste:   mean={statistics.fmean(p_list):.3f} ms | median={statistics.median(p_list):.3f} ms")
    print(f"  Total:   mean={statistics.fmean(tot_list):.3f} ms | median={statistics.median(tot_list):.3f} ms")
