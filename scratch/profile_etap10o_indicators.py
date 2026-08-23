import os
import sys
import copy
import json
import time
import numpy as np
from pathlib import Path
from datetime import datetime, timezone, timedelta
from PIL import Image, ImageChops

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.gui.telemetry_manager import TelemetryDataManager
from src.indicators.frame_data import prepare_overlay_frame_data
import src.indicators.compositor as compositor
from src.indicators.compositor import compose_overlay
from src.indicators.dispatcher import render_value_indicator
from src.indicators.bar import _render_bar_indicator
from src.ffmpeg.amd_native_exporter import _ordered_map_layout_parts
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
canvas_w, canvas_h = 1280, 720
font_path = ""
fps = 60.0
total_frames = 120

below_layout, above_layout, after_keys = _ordered_map_layout_parts(v10_layout)

print("BELOW indicators:", list(below_layout.get("indicators", {}).keys()))
print("ABOVE indicators:", list(above_layout.get("indicators", {}).keys()))

# Build precomputed frame data
frames_kw = []
for i in range(total_frames):
    dt = start_dt + timedelta(seconds=i / fps)
    kw = prepare_overlay_frame_data(
        target_dt=dt, start_dt_utc=start_dt, tz_offset_hours=2.0, layout=v10_layout,
        speed_samples=telemetry.speed_samples, track_samples=telemetry.track_samples,
        alt_samples=telemetry.alt_samples, iso_samples=telemetry.iso_samples,
        exposure_samples=telemetry.exposure_samples, temperature_samples=telemetry.temperature_samples,
        fit_data=telemetry.fit_data, gps_track=telemetry.get_gps_track_for_source("fit"),
        resolve_cache_value=lambda k, src, d, ind=None: telemetry.resolve_value(k, d, source=src),
    )
    frames_kw.append(kw)

# Profile data structures
below_widget_keys = list(below_layout.get("indicators", {}).keys())
above_widget_keys = list(above_layout.get("indicators", {}).keys())

stats_below = {k: {"render": [], "paste": [], "total": []} for k in below_widget_keys}
stats_above = {k: {"render": [], "rot": [], "paste": [], "total": []} for k in above_widget_keys}

below_compose_totals = []
above_compose_totals = []

alt_rot_breakdown = {
    "render": [], "rotate_call": [], "paste_composite": [], "total": []
}

compass_breakdown = {
    "render": [], "rotation": [], "paste_composite": [], "total": []
}

vp_breakdown = {
    "render": [], "text_val": [], "paste_composite": [], "total": []
}

warmup_data = {
    "above_1_10": [], "above_11_120": [],
    "below_1_10": [], "below_11_120": [],
    "alt_rot_1_10": [], "alt_rot_11_120": [],
}

# Run 120 frames with detailed per-widget hook
for idx in range(total_frames):
    kw = frames_kw[idx]
    is_warmup = (idx < 10)
    
    # 1. BELOW compose total
    t0 = time.perf_counter()
    b_bboxes = {}
    b_img = compose_overlay(canvas_w, canvas_h, below_layout, "", _bboxes=b_bboxes, reuse_canvas="below", **kw)
    t1 = time.perf_counter()
    b_tot = (t1 - t0) * 1000.0
    below_compose_totals.append(b_tot)
    if is_warmup:
        warmup_data["below_1_10"].append(b_tot)
    else:
        warmup_data["below_11_120"].append(b_tot)

    # 2. ABOVE compose total
    t0 = time.perf_counter()
    a_bboxes = {}
    a_img = compose_overlay(canvas_w, canvas_h, above_layout, "", _bboxes=a_bboxes, reuse_canvas="above", **kw)
    t1 = time.perf_counter()
    a_tot = (t1 - t0) * 1000.0
    above_compose_totals.append(a_tot)
    if is_warmup:
        warmup_data["above_1_10"].append(a_tot)
    else:
        warmup_data["above_11_120"].append(a_tot)

    # 3. Individual BELOW widgets
    for k in below_widget_keys:
        single_l = dict(below_layout, indicators={k: below_layout["indicators"][k]})
        t0 = time.perf_counter()
        _bb = {}
        _img = compose_overlay(canvas_w, canvas_h, single_l, "", _bboxes=_bb, reuse_canvas=False, **kw)
        t1 = time.perf_counter()
        tot = (t1 - t0) * 1000.0
        stats_below[k]["total"].append(tot)

    # 4. Individual ABOVE widgets
    for k in above_widget_keys:
        single_l = dict(above_layout, indicators={k: above_layout["indicators"][k]})
        t0 = time.perf_counter()
        _bb = {}
        _img = compose_overlay(canvas_w, canvas_h, single_l, "", _bboxes=_bb, reuse_canvas=False, **kw)
        t1 = time.perf_counter()
        tot = (t1 - t0) * 1000.0
        stats_above[k]["total"].append(tot)

    # Micro-profile Altitude rotated paste
    alt_cfg = v10_layout["indicators"]["alt_visual"]
    alt_val = kw["alt_value"]
    t0 = time.perf_counter()
    alt_tile, _, _, _ = _render_bar_indicator(
        canvas_w, canvas_h, v10_layout, "", "alt_visual", alt_val, "m", "ALTITUDE",
        alt_cfg, min(canvas_w, canvas_h), 1, 9, None, 0.0, 1000.0, 5, 1, 115, 1,
    )
    t1 = time.perf_counter()
    t_rot0 = time.perf_counter()
    alt_rot = alt_tile.rotate(-90.0, expand=True, resample=Image.BICUBIC)
    t_rot1 = time.perf_counter()
    t_p0 = time.perf_counter()
    dummy_c = Image.new("RGBA", (canvas_w, canvas_h), (0, 0, 0, 0))
    dummy_c.alpha_composite(alt_rot, (10, 10))
    t_p1 = time.perf_counter()
    r_ms = (t1 - t0) * 1000.0
    rot_ms = (t_rot1 - t_rot0) * 1000.0
    p_ms = (t_p1 - t_p0) * 1000.0
    tot_alt = (t_p1 - t0) * 1000.0
    alt_rot_breakdown["render"].append(r_ms)
    alt_rot_breakdown["rotate_call"].append(rot_ms)
    alt_rot_breakdown["paste_composite"].append(p_ms)
    alt_rot_breakdown["total"].append(tot_alt)
    if is_warmup:
        warmup_data["alt_rot_1_10"].append(tot_alt)
    else:
        warmup_data["alt_rot_11_120"].append(tot_alt)

    # Micro-profile Compass
    comp_cfg = v10_layout["indicators"]["compass"]
    heading_val = kw["map_heading"]
    t0 = time.perf_counter()
    comp_tile, cx, cy, _ = render_value_indicator(
        canvas_w, canvas_h, v10_layout, "", "compass", heading_val or 0.0, "°", "COMPASS"
    )
    t1 = time.perf_counter()
    t_p0 = time.perf_counter()
    if comp_tile:
        dummy_c.alpha_composite(comp_tile, (cx, cy))
    t_p1 = time.perf_counter()
    compass_breakdown["render"].append((t1 - t0) * 1000.0)
    compass_breakdown["rotation"].append(0.0)
    compass_breakdown["paste_composite"].append((t_p1 - t_p0) * 1000.0)
    compass_breakdown["total"].append((t_p1 - t0) * 1000.0)

    # Micro-profile Virtual Power
    vp_cfg = v10_layout["indicators"]["fit_curVpower_text"]
    vp_val = kw["power_value"]
    t0 = time.perf_counter()
    vp_tile, vx, vy, _ = render_value_indicator(
        canvas_w, canvas_h, v10_layout, "", "fit_curVpower_text", vp_val or 0.0, "W", "VIRTUAL POWER"
    )
    t1 = time.perf_counter()
    t_p0 = time.perf_counter()
    if vp_tile:
        dummy_c.alpha_composite(vp_tile, (vx, vy))
    t_p1 = time.perf_counter()
    vp_breakdown["render"].append((t1 - t0) * 1000.0)
    vp_breakdown["text_val"].append((t1 - t0) * 1000.0)
    vp_breakdown["paste_composite"].append((t_p1 - t_p0) * 1000.0)
    vp_breakdown["total"].append((t_p1 - t0) * 1000.0)

# Isolated Rotation Microbenchmark
alt_img, _, _, _ = _render_bar_indicator(
    canvas_w, canvas_h, v10_layout, "", "alt_visual", 500.0, "m", "ALTITUDE",
    alt_cfg, min(canvas_w, canvas_h), 1, 9, None, 0.0, 1000.0, 5, 1, 115, 1,
)
N_ROTS = 1000
t0 = time.perf_counter()
for _ in range(N_ROTS):
    _r1 = alt_img.rotate(-90.0, expand=True, resample=Image.BICUBIC)
t1 = time.perf_counter()
rot_bicubic_ms = (t1 - t0) * 1000.0 / N_ROTS

t0 = time.perf_counter()
for _ in range(N_ROTS):
    _r2 = alt_img.rotate(-90.0, expand=True, resample=Image.NEAREST)
t1 = time.perf_counter()
rot_nearest_ms = (t1 - t0) * 1000.0 / N_ROTS

t0 = time.perf_counter()
for _ in range(N_ROTS):
    _r3 = alt_img.transpose(Image.Transpose.ROTATE_270)
t1 = time.perf_counter()
rot_transpose_ms = (t1 - t0) * 1000.0 / N_ROTS

diff_box = None
try:
    r_rot = alt_img.rotate(-90.0, expand=True, resample=Image.NEAREST)
    r_tr = alt_img.transpose(Image.Transpose.ROTATE_270)
    diff = ImageChops.difference(r_rot, r_tr)
    diff_box = diff.getbbox()
except Exception as e:
    diff_box = str(e)

def calc_stats(arr):
    if not arr:
        return 0.0, 0.0, 0.0
    a = np.array(arr)
    return float(np.mean(a)), float(np.median(a)), float(np.percentile(a, 95))

print("\n" + "="*80)
print("FRESH PER-WIDGET PROFILE — BELOW (120 frames)")
print("="*80)
for k, v in stats_below.items():
    m, med, p95 = calc_stats(v["total"])
    print(f"  {k:<25}: mean {m:.3f} ms | median {med:.3f} ms | p95 {p95:.3f} ms")

print("\n" + "="*80)
print("FRESH PER-WIDGET PROFILE — ABOVE (120 frames)")
print("="*80)
for k, v in stats_above.items():
    m, med, p95 = calc_stats(v["total"])
    print(f"  {k:<25}: mean {m:.3f} ms | median {med:.3f} ms | p95 {p95:.3f} ms")

print("\n" + "="*80)
print("ALTITUDE ROTATED PASTE MICRO-BREAKDOWN (120 frames)")
print("="*80)
for k, v in alt_rot_breakdown.items():
    m, med, p95 = calc_stats(v)
    print(f"  {k:<20}: mean {m:.3f} ms | median {med:.3f} ms | p95 {p95:.3f} ms")

print("\n" + "="*80)
print("COMPASS MICRO-BREAKDOWN (120 frames)")
print("="*80)
for k, v in compass_breakdown.items():
    m, med, p95 = calc_stats(v)
    print(f"  {k:<20}: mean {m:.3f} ms | median {med:.3f} ms | p95 {p95:.3f} ms")

print("\n" + "="*80)
print("VIRTUAL POWER MICRO-BREAKDOWN (120 frames)")
print("="*80)
for k, v in vp_breakdown.items():
    m, med, p95 = calc_stats(v)
    print(f"  {k:<20}: mean {m:.3f} ms | median {med:.3f} ms | p95 {p95:.3f} ms")

print("\n" + "="*80)
print("ROTATION ISOLATED MICROBENCHMARK (1000 iterations)")
print("="*80)
print(f"  Image.rotate(resample=BICUBIC): {rot_bicubic_ms:.3f} ms/call")
print(f"  Image.rotate(resample=NEAREST): {rot_nearest_ms:.3f} ms/call")
print(f"  Image.transpose(ROTATE_270)   : {rot_transpose_ms:.3f} ms/call (Speedup: {rot_bicubic_ms / max(0.0001, rot_transpose_ms):.1f}x)")
print(f"  Pixel Parity (NEAREST vs TRANSPOSE) diff bbox: {diff_box}")

# Residuals
m_b_tot, med_b_tot, _ = calc_stats(below_compose_totals)
sum_below_widgets = sum(calc_stats(stats_below[k]["total"])[0] for k in below_widget_keys)
below_residual = max(0.0, m_b_tot - sum_below_widgets)

m_a_tot, med_a_tot, _ = calc_stats(above_compose_totals)
sum_above_widgets = sum(calc_stats(stats_above[k]["total"])[0] for k in above_widget_keys)
above_residual = max(0.0, m_a_tot - sum_above_widgets)

print("\n" + "="*80)
print("RESIDUALS")
print("="*80)
print(f"  BELOW total: {m_b_tot:.3f} ms | SUM widgets: {sum_below_widgets:.3f} ms | Residual: {below_residual:.3f} ms")
print(f"  ABOVE total: {m_a_tot:.3f} ms | SUM widgets: {sum_above_widgets:.3f} ms | Residual: {above_residual:.3f} ms")

summary_out = {
    "timings_below": {k: calc_stats(v["total"]) for k, v in stats_below.items()},
    "timings_above": {k: calc_stats(v["total"]) for k, v in stats_above.items()},
    "alt_rot_steps": {k: calc_stats(v) for k, v in alt_rot_breakdown.items()},
    "compass_breakdown": {k: calc_stats(v) for k, v in compass_breakdown.items()},
    "vp_breakdown": {k: calc_stats(v) for k, v in vp_breakdown.items()},
    "below_compose_totals": calc_stats(below_compose_totals),
    "above_compose_totals": calc_stats(above_compose_totals),
    "below_residual": below_residual,
    "above_residual": above_residual,
    "warmup_data": {k: calc_stats(v) for k, v in warmup_data.items()},
    "rotation_microbenchmark": {
        "bicubic_ms": rot_bicubic_ms,
        "nearest_ms": rot_nearest_ms,
        "transpose_ms": rot_transpose_ms,
        "diff_box": diff_box,
    },
}

with open(root / "scratch" / "profile_etap10o_indicator_summary.json", "w", encoding="utf-8") as f:
    json.dump(summary_out, f, indent=2)
print("Saved summary to scratch/profile_etap10o_indicator_summary.json")
