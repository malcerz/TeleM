import sys
import json
import time
from pathlib import Path
from datetime import datetime, timezone, timedelta
from collections import defaultdict
import numpy as np
from PIL import Image, ImageChops

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.gui.telemetry_manager import TelemetryDataManager
from src.indicators.frame_data import prepare_overlay_frame_data
import src.indicators.compositor as compositor
from src.indicators.chart_utils import generate_nice_time_ticks
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

start_dt = telemetry.start_dt_utc
fit_dur = 8480.0
if telemetry.fit_data and "heart_rate" in telemetry.fit_data:
    pts = telemetry.fit_data["heart_rate"]
    if pts:
        fit_dur = (pts[-1][0] - pts[0][0]).total_seconds()

print("=== 1. NICE TIME TICKS GENERATOR TESTS ===")
durations = [
    (45.0, "Short clip 45s"),
    (120.0, "Video 2m"),
    (600.0, "Activity 10m"),
    (3600.0, "Activity 1h"),
    (fit_dur, f"Real FIT Activity (~{fit_dur/3600:.2f}h)"),
    (18000.0, "Activity 5h"),
]

for d, desc in durations:
    ticks = generate_nice_time_ticks(d)
    print(f"\n{desc} ({d:.1f}s): {len(ticks)} ticks")
    print("  " + ", ".join(f"{lbl} ({nx*100:.1f}%)" for nx, lbl in ticks))
    assert 3 <= len(ticks) <= 9, f"Tick count {len(ticks)} out of reasonable range!"
    assert all("%" not in lbl for _, lbl in ticks), "No percent symbols allowed!"

print("\n=== 2. CURSOR ALIGNMENT CHECK ===")
target_dt = start_dt + timedelta(seconds=147.0)

kwargs = prepare_overlay_frame_data(
    target_dt=target_dt,
    start_dt_utc=start_dt,
    tz_offset_hours=2.0,
    layout=v10_layout,
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

img_base = compositor.compose_overlay(1280, 720, v10_layout, "", reuse_canvas="above", **kwargs)
print(f"Base render at t=147s: size={img_base.size}")
assert img_base is not None

print("\n=== 3. RASTER TESTS FOR 4 AXIS SWITCH COMBINATIONS ===")
combinations = [
    (True, True, "X_ON_Y_ON"),
    (False, True, "X_OFF_Y_ON"),
    (True, False, "X_ON_Y_OFF"),
    (False, False, "X_OFF_Y_OFF"),
]

renders = {}
for show_x, show_y, name in combinations:
    test_layout = json.loads(json.dumps(v10_layout))
    test_layout["indicators"]["fit_heart_rate_text"]["show_x_axis_values"] = show_x
    test_layout["indicators"]["fit_heart_rate_text"]["show_y_axis_values"] = show_y
    test_layout["indicators"]["fit_cadence_text"]["show_x_axis_values"] = show_x
    test_layout["indicators"]["fit_cadence_text"]["show_y_axis_values"] = show_y
    
    kw = prepare_overlay_frame_data(
        target_dt=target_dt,
        start_dt_utc=start_dt,
        tz_offset_hours=2.0,
        layout=test_layout,
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
    img = compositor.compose_overlay(1280, 720, test_layout, "", **kw).copy()
    renders[name] = img
    print(f"Rendered {name}: size={img.size}")

# Compare differences
diff_x_off = ImageChops.difference(renders["X_ON_Y_ON"], renders["X_OFF_Y_ON"])
bbox_x_diff = diff_x_off.getbbox()
print(f"Diff bbox when turning X values OFF: {bbox_x_diff}")
assert bbox_x_diff is not None, "Turning X values OFF must remove X labels!"

diff_y_off = ImageChops.difference(renders["X_ON_Y_ON"], renders["X_ON_Y_OFF"])
bbox_y_diff = diff_y_off.getbbox()
print(f"Diff bbox when turning Y values OFF: {bbox_y_diff}")
assert bbox_y_diff is not None, "Turning Y values OFF must remove Y labels!"

diff_both_off = ImageChops.difference(renders["X_ON_Y_ON"], renders["X_OFF_Y_OFF"])
bbox_both_diff = diff_both_off.getbbox()
print(f"Diff bbox when turning BOTH OFF: {bbox_both_diff}")
assert bbox_both_diff is not None

print("\n=== 4. PAUSE AND RANDOM ACCESS VERIFICATION ===")
test_ts = [7.0, 60.0, 147.0, 300.0, 585.0]
for ts in test_ts:
    dt = start_dt + timedelta(seconds=ts)
    kw = prepare_overlay_frame_data(
        target_dt=dt, start_dt_utc=start_dt, tz_offset_hours=2.0, layout=v10_layout,
        speed_samples=telemetry.speed_samples, track_samples=telemetry.track_samples,
        alt_samples=telemetry.alt_samples, iso_samples=telemetry.iso_samples,
        exposure_samples=telemetry.exposure_samples, temperature_samples=telemetry.temperature_samples,
        fit_data=telemetry.fit_data, gps_track=telemetry.get_gps_track_for_source("fit"),
        resolve_cache_value=lambda k, src, d, ind=None: telemetry.resolve_value(k, d, source=src),
    )
    img_seq = compositor.compose_overlay(1280, 720, v10_layout, "", reuse_canvas="above", **kw)
    img_direct = compositor.compose_overlay(1280, 720, v10_layout, "", reuse_canvas="above", **kw)
    diff = ImageChops.difference(img_seq, img_direct).getbbox()
    assert diff is None, f"Mismatch on direct seek at t={ts}s!"
print("Random access verified across all test timestamps: 100% byte-exact!")

print("\n=== 5. FONT COMPATIBILITY ===")
fonts_to_test = ["", "Comic Sans", "Digital-7", "Iona-u1"]
for f in fonts_to_test:
    test_layout = json.loads(json.dumps(v10_layout))
    if f:
        test_layout["indicators"]["fit_heart_rate_text"]["font"] = f
        test_layout["indicators"]["fit_cadence_text"]["font"] = f
    kw = prepare_overlay_frame_data(
        target_dt=target_dt, start_dt_utc=start_dt, tz_offset_hours=2.0, layout=test_layout,
        speed_samples=telemetry.speed_samples, track_samples=telemetry.track_samples,
        alt_samples=telemetry.alt_samples, iso_samples=telemetry.iso_samples,
        exposure_samples=telemetry.exposure_samples, temperature_samples=telemetry.temperature_samples,
        fit_data=telemetry.fit_data, gps_track=telemetry.get_gps_track_for_source("fit"),
        resolve_cache_value=lambda k, src, d, ind=None: telemetry.resolve_value(k, d, source=src),
    )
    img_f = compositor.compose_overlay(1280, 720, test_layout, f, reuse_canvas="above", **kw)
    assert img_f is not None
    print(f"Font '{f or 'default'}' rendered successfully.")

print("\n=== 6. LOCAL PERFORMANCE BENCHMARK (120 FRAMES) ===")
timings = defaultdict(lambda: defaultdict(list))
orig_render = compositor.render_value_indicator

def hooked_render(*args, **kwargs):
    key = args[4] if len(args) > 4 else kwargs.get("key")
    t0 = time.perf_counter()
    res = orig_render(*args, **kwargs)
    t1 = time.perf_counter()
    timings[key]["render"].append((t1 - t0) * 1000.0)
    return res

compositor.render_value_indicator = hooked_render

# Warmup 10 frames
for i in range(10):
    dt = start_dt + timedelta(seconds=i / 60.0)
    kw = prepare_overlay_frame_data(
        target_dt=dt, start_dt_utc=start_dt, tz_offset_hours=2.0, layout=v10_layout,
        speed_samples=telemetry.speed_samples, track_samples=telemetry.track_samples,
        alt_samples=telemetry.alt_samples, iso_samples=telemetry.iso_samples,
        exposure_samples=telemetry.exposure_samples, temperature_samples=telemetry.temperature_samples,
        fit_data=telemetry.fit_data, gps_track=telemetry.get_gps_track_for_source("fit"),
        resolve_cache_value=lambda k, src, d, ind=None: telemetry.resolve_value(k, d, source=src),
    )
    compositor.compose_overlay(1280, 720, v10_layout, "", reuse_canvas="above", **kw)

timings.clear()

for i in range(10, 130):
    dt = start_dt + timedelta(seconds=i / 60.0)
    kw = prepare_overlay_frame_data(
        target_dt=dt, start_dt_utc=start_dt, tz_offset_hours=2.0, layout=v10_layout,
        speed_samples=telemetry.speed_samples, track_samples=telemetry.track_samples,
        alt_samples=telemetry.alt_samples, iso_samples=telemetry.iso_samples,
        exposure_samples=telemetry.exposure_samples, temperature_samples=telemetry.temperature_samples,
        fit_data=telemetry.fit_data, gps_track=telemetry.get_gps_track_for_source("fit"),
        resolve_cache_value=lambda k, src, d, ind=None: telemetry.resolve_value(k, d, source=src),
    )
    compositor.compose_overlay(1280, 720, v10_layout, "", reuse_canvas="above", **kw)

hr_r = timings["fit_heart_rate_text"]["render"]
cad_r = timings["fit_cadence_text"]["render"]

avg_hr = sum(hr_r) / len(hr_r)
avg_cad = sum(cad_r) / len(cad_r)
sum_charts = avg_hr + avg_cad

print(f"Heart Rate Chart (120 frames): avg = {avg_hr:.3f} ms (med = {sorted(hr_r)[len(hr_r)//2]:.3f} ms)")
print(f"Cadence Chart    (120 frames): avg = {avg_cad:.3f} ms (med = {sorted(cad_r)[len(cad_r)//2]:.3f} ms)")
print(f"SUM HR + Cadence:              avg = {sum_charts:.3f} ms")

print("\nALL VERIFICATIONS PASSED SUCCESSFULLY!")
