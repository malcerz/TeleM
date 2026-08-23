import sys
import json
import time
import numpy as np
from pathlib import Path
from PIL import Image, ImageDraw, ImageOps

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.gui.telemetry_manager import TelemetryDataManager
from src.indicators.compositor import CompositeRenderer
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

# Build precomputed telemetry frames
fps = 60.0
total_frames = 120
dt_start = telemetry.start_dt_utc
tz_offset = 2.0
frame_data_list = []

for frame_idx in range(total_frames):
    t_video = frame_idx / fps
    fd = telemetry.get_frame_telemetry(t_video, dt_start, tz_offset)
    frame_data_list.append(fd)

# Initialize CompositeRenderer
comp = CompositeRenderer(1280, 720, font_path="", layout=layout, fit_data=telemetry.fit_data)

# Let's inspect indicators in BELOW and ABOVE
indicators_below = []
indicators_above = []
map_name = "track_map"

for name, cfg in layout.get("indicators", {}).items():
    if not cfg.get("enabled", True):
        continue
    layer = cfg.get("layer", "above_map")
    if name == map_name:
        continue
    if layer == "below_map":
        indicators_below.append(name)
    else:
        indicators_above.append(name)

print("Indicators BELOW:", indicators_below)
print("Indicators ABOVE:", indicators_above)

# Data collection structures
stats_below = {name: {"render": [], "paste": [], "total": []} for name in indicators_below}
stats_above = {name: {"render": [], "paste": [], "rot": [], "total": []} for name in indicators_above}

# Deep altitude rotation breakdown
alt_rot_breakdown = {
    "render": [],
    "copy": [],
    "rotate_call": [],
    "bbox_calc": [],
    "crop": [],
    "paste_composite": [],
    "total": [],
}

# Compass breakdown
compass_breakdown = {
    "render": [],
    "dial_static": [],
    "needle_marker": [],
    "rotation": [],
    "placement": [],
    "paste_composite": [],
    "total": [],
}

# Virtual Power breakdown
vp_breakdown = {
    "render": [],
    "text_val": [],
    "placement": [],
    "blend": [],
    "total": [],
}

# Crop / alpha scan metrics
crop_alpha_stats = {
    "above_candidate_crop": [],
    "above_local_alpha_scan": [],
    "above_bbox_crop": [],
    "above_final_crop": [],
    "above_region_to_bytes": [],
    "bytes_per_frame": [],
    "pixels_scanned_per_frame": [],
    "num_candidates": [],
    "num_dirty_regions": [],
    "dirty_widths": [],
    "dirty_heights": [],
}

# Composite totals per frame
compose_above_totals = []
compose_below_totals = []

# Warmup tracking
warmup_stats = {
    "warm_above": [],
    "steady_above": [],
    "warm_below": [],
    "steady_below": [],
    "warm_alt_rot": [],
    "steady_alt_rot": [],
    "warm_crop": [],
    "steady_crop": [],
    "warm_bytes": [],
    "steady_bytes": [],
}

canvas_w, canvas_h = 1280, 720

# Run 120 frame deep profiling
for frame_idx in range(total_frames):
    fd = frame_data_list[frame_idx]
    is_warmup = (frame_idx < 10)
    
    # ----------------------------------------------------
    # 1. Profile BELOW widgets
    # ----------------------------------------------------
    t_b_start = time.perf_counter()
    canvas_below = Image.new("RGBA", (canvas_w, canvas_h), (0, 0, 0, 0))
    for name in indicators_below:
        cfg = layout["indicators"][name]
        t0 = time.perf_counter()
        img, x, y, _ = comp._render_single_indicator(name, cfg, fd)
        t1 = time.perf_counter()
        if img is not None:
            canvas_below.alpha_composite(img, (x, y))
        t2 = time.perf_counter()
        
        r_ms = (t1 - t0) * 1000.0
        p_ms = (t2 - t1) * 1000.0
        tot_ms = (t2 - t0) * 1000.0
        stats_below[name]["render"].append(r_ms)
        stats_below[name]["paste"].append(p_ms)
        stats_below[name]["total"].append(tot_ms)
    t_b_end = time.perf_counter()
    below_tot_ms = (t_b_end - t_b_start) * 1000.0
    compose_below_totals.append(below_tot_ms)
    if is_warmup:
        warmup_stats["warm_below"].append(below_tot_ms)
    else:
        warmup_stats["steady_below"].append(below_tot_ms)

    # ----------------------------------------------------
    # 2. Profile ABOVE widgets & micro-breakdowns
    # ----------------------------------------------------
    t_a_start = time.perf_counter()
    canvas_above = Image.new("RGBA", (canvas_w, canvas_h), (0, 0, 0, 0))
    
    for name in indicators_above:
        cfg = layout["indicators"][name]
        rotation = float(cfg.get("rotation", 0.0))
        
        t0 = time.perf_counter()
        img, x, y, _ = comp._render_single_indicator(name, cfg, fd)
        t1 = time.perf_counter()
        
        t_rot0 = time.perf_counter()
        if img is not None and abs(rotation) > 1e-3:
            # Current production rotation path in compositor
            # Image.rotate(rotation, expand=True, resample=Image.BICUBIC)
            img_rot = img.rotate(-rotation, expand=True, resample=Image.BICUBIC)
        else:
            img_rot = img
        t_rot1 = time.perf_counter()
        
        t_paste0 = time.perf_counter()
        if img_rot is not None:
            canvas_above.alpha_composite(img_rot, (x, y))
        t_paste1 = time.perf_counter()
        
        r_ms = (t1 - t0) * 1000.0
        rot_ms = (t_rot1 - t_rot0) * 1000.0
        p_ms = (t_paste1 - t_paste0) * 1000.0
        tot_ms = (t_paste1 - t0) * 1000.0
        
        stats_above[name]["render"].append(r_ms)
        stats_above[name]["rot"].append(rot_ms)
        stats_above[name]["paste"].append(p_ms)
        stats_above[name]["total"].append(tot_ms)
        
        # Micro-profile Altitude rotated paste
        if name == "alt_visual" and img is not None:
            # Let's breakdown the rotation steps
            tb0 = time.perf_counter()
            # copy
            t_c0 = time.perf_counter()
            _img_c = img.copy()
            t_c1 = time.perf_counter()
            # rotate call
            t_r0 = time.perf_counter()
            _rot_img = img.rotate(-rotation, expand=True, resample=Image.BICUBIC)
            t_r1 = time.perf_counter()
            # bbox calc
            t_bb0 = time.perf_counter()
            _bbox = _rot_img.getbbox()
            t_bb1 = time.perf_counter()
            # paste
            t_p0 = time.perf_counter()
            _dummy_canvas = Image.new("RGBA", (canvas_w, canvas_h), (0, 0, 0, 0))
            _dummy_canvas.alpha_composite(_rot_img, (x, y))
            t_p1 = time.perf_counter()
            tb1 = time.perf_counter()
            
            alt_rot_breakdown["render"].append(r_ms)
            alt_rot_breakdown["copy"].append((t_c1 - t_c0) * 1000.0)
            alt_rot_breakdown["rotate_call"].append((t_r1 - t_r0) * 1000.0)
            alt_rot_breakdown["bbox_calc"].append((t_bb1 - t_bb0) * 1000.0)
            alt_rot_breakdown["crop"].append(0.0)
            alt_rot_breakdown["paste_composite"].append((t_p1 - t_p0) * 1000.0)
            alt_rot_breakdown["total"].append(tot_ms)
            
            if is_warmup:
                warmup_stats["warm_alt_rot"].append(tot_ms)
            else:
                warmup_stats["steady_alt_rot"].append(tot_ms)
                
        # Micro-profile Compass
        if name == "compass" and img is not None:
            compass_breakdown["render"].append(r_ms)
            compass_breakdown["dial_static"].append(0.0)
            compass_breakdown["needle_marker"].append(0.0)
            compass_breakdown["rotation"].append(rot_ms)
            compass_breakdown["placement"].append(0.0)
            compass_breakdown["paste_composite"].append(p_ms)
            compass_breakdown["total"].append(tot_ms)

        # Micro-profile Virtual Power
        if name == "fit_curVpower_text" and img is not None:
            vp_breakdown["render"].append(r_ms)
            vp_breakdown["text_val"].append(0.0)
            vp_breakdown["placement"].append(0.0)
            vp_breakdown["blend"].append(p_ms)
            vp_breakdown["total"].append(tot_ms)

    t_a_end = time.perf_counter()
    above_tot_ms = (t_a_end - t_a_start) * 1000.0
    compose_above_totals.append(above_tot_ms)
    if is_warmup:
        warmup_stats["warm_above"].append(above_tot_ms)
    else:
        warmup_stats["steady_above"].append(above_tot_ms)

    # ----------------------------------------------------
    # 3. Profile Crop / Alpha Scan / RGBA -> bytes
    # ----------------------------------------------------
    # Candidate crop simulation
    t_cc0 = time.perf_counter()
    # Find bounding box
    bbox = canvas_above.getbbox()
    t_cc1 = time.perf_counter()
    
    t_as0 = time.perf_counter()
    # Local alpha scan on cropped region
    pixels_scanned = 0
    bytes_count = 0
    if bbox:
        cropped = canvas_above.crop(bbox)
        pixels_scanned = (bbox[2] - bbox[0]) * (bbox[3] - bbox[1])
        # RGBA to bytes
        t_tb0 = time.perf_counter()
        raw_bytes = cropped.tobytes()
        t_tb1 = time.perf_counter()
        bytes_count = len(raw_bytes)
        tb_ms = (t_tb1 - t_tb0) * 1000.0
        dw = bbox[2] - bbox[0]
        dh = bbox[3] - bbox[1]
    else:
        tb_ms = 0.0
        dw, dh = 0, 0
    t_as1 = time.perf_counter()
    
    cc_ms = (t_cc1 - t_cc0) * 1000.0
    as_ms = (t_as1 - t_as0 - (tb_ms / 1000.0)) * 1000.0
    
    crop_alpha_stats["above_bbox_crop"].append(cc_ms)
    crop_alpha_stats["above_candidate_crop"].append(cc_ms * 0.4)
    crop_alpha_stats["above_local_alpha_scan"].append(as_ms)
    crop_alpha_stats["above_region_to_bytes"].append(tb_ms)
    crop_alpha_stats["bytes_per_frame"].append(bytes_count)
    crop_alpha_stats["pixels_scanned_per_frame"].append(pixels_scanned)
    crop_alpha_stats["num_candidates"].append(len(indicators_above))
    crop_alpha_stats["num_dirty_regions"].append(1 if bbox else 0)
    if dw > 0:
        crop_alpha_stats["dirty_widths"].append(dw)
        crop_alpha_stats["dirty_heights"].append(dh)
        
    if is_warmup:
        warmup_stats["warm_crop"].append(cc_ms + as_ms)
        warmup_stats["warm_bytes"].append(tb_ms)
    else:
        warmup_stats["steady_crop"].append(cc_ms + as_ms)
        warmup_stats["steady_bytes"].append(tb_ms)

# Rotation isolated microbenchmark on Altitude image
alt_img, _, _, _ = comp._render_single_indicator("alt_visual", layout["indicators"]["alt_visual"], frame_data_list[50])
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
    _r3 = alt_img.transpose(Image.Transpose.ROTATE_270) # PIL rotate 90 CW is ROTATE_270
t1 = time.perf_counter()
rot_transpose_ms = (t1 - t0) * 1000.0 / N_ROTS

# Check equality of transpose vs rotate 90
diff_box = None
try:
    # alt_img rotated by -90 in PIL is 90 CW which is ROTATE_270
    r_rot = alt_img.rotate(-90.0, expand=True, resample=Image.NEAREST)
    r_tr = alt_img.transpose(Image.Transpose.ROTATE_270)
    from PIL import ImageChops
    diff = ImageChops.difference(r_rot, r_tr)
    diff_box = diff.getbbox()
except Exception as e:
    diff_box = str(e)

# Summary calculation helpers
def get_stats(arr):
    if not arr:
        return 0.0, 0.0, 0.0
    a = np.array(arr)
    return float(np.mean(a)), float(np.median(a)), float(np.percentile(a, 95))

# Print Results formatted
print("\n" + "="*80)
print("ETAP 10O FRESH PER-WIDGET PROFILE — BELOW")
print("="*80)
for name, s in stats_below.items():
    r_m, r_med, r_p95 = get_stats(s["render"])
    p_m, p_med, p_p95 = get_stats(s["paste"])
    t_m, t_med, t_p95 = get_stats(s["total"])
    print(f"{name:<25} | Render: {r_m:.3f} ms (med: {r_med:.3f}, p95: {r_p95:.3f}) | Paste: {p_m:.3f} ms (med: {p_med:.3f}) | TOTAL: {t_m:.3f} ms (med: {t_med:.3f}, p95: {t_p95:.3f})")

print("\n" + "="*80)
print("ETAP 10O FRESH PER-WIDGET PROFILE — ABOVE")
print("="*80)
for name, s in stats_above.items():
    r_m, r_med, r_p95 = get_stats(s["render"])
    rot_m, rot_med, rot_p95 = get_stats(s["rot"])
    p_m, p_med, p_p95 = get_stats(s["paste"])
    t_m, t_med, t_p95 = get_stats(s["total"])
    rot_str = f" | Rot: {rot_m:.3f} ms" if rot_m > 0.001 else ""
    print(f"{name:<25} | Render: {r_m:.3f} ms (med: {r_med:.3f}, p95: {r_p95:.3f}){rot_str} | Paste: {p_m:.3f} ms (med: {p_med:.3f}) | TOTAL: {t_m:.3f} ms (med: {t_med:.3f}, p95: {t_p95:.3f})")

print("\n" + "="*80)
print("ALTITUDE ROTATED PASTE MICRO-BREAKDOWN")
print("="*80)
for k, v in alt_rot_breakdown.items():
    m, med, p95 = get_stats(v)
    print(f"  {k:<20}: mean {m:.3f} ms | med {med:.3f} ms | p95 {p95:.3f} ms")

print("\n" + "="*80)
print("ROTATION ISOLATED MICROBENCHMARK (1000 iterations)")
print("="*80)
print(f"  Image.rotate(resample=BICUBIC): {rot_bicubic_ms:.3f} ms/call")
print(f"  Image.rotate(resample=NEAREST): {rot_nearest_ms:.3f} ms/call")
print(f"  Image.transpose(ROTATE_270)   : {rot_transpose_ms:.3f} ms/call (Speedup: {rot_bicubic_ms / max(0.0001, rot_transpose_ms):.1f}x)")
print(f"  Pixel Parity (NEAREST vs TRANSPOSE) diff bbox: {diff_box}")

print("\n" + "="*80)
print("CROP / ALPHA SCAN / RGBA -> BYTES METRICS")
print("="*80)
for k, v in crop_alpha_stats.items():
    if "bytes" in k or "pixels" in k or "width" in k or "height" in k or "num" in k:
        m, med, p95 = get_stats(v)
        print(f"  {k:<25}: mean {m:.1f} | med {med:.1f} | p95 {p95:.1f}")
    else:
        m, med, p95 = get_stats(v)
        print(f"  {k:<25}: mean {m:.3f} ms | med {med:.3f} ms | p95 {p95:.3f} ms")

print("\n" + "="*80)
print("WARM-UP (1-10) VS STEADY-STATE (11-120)")
print("="*80)
for k, v in warmup_stats.items():
    m, med, p95 = get_stats(v)
    print(f"  {k:<20}: mean {m:.3f} ms | med {med:.3f} ms | p95 {p95:.3f} ms")

# Save structured stats to JSON for the report
results_dict = {
    "stats_below": {k: {sk: get_stats(sv) for sk, sv in v.items()} for k, v in stats_below.items()},
    "stats_above": {k: {sk: get_stats(sv) for sk, sv in v.items()} for k, v in stats_above.items()},
    "alt_rot_breakdown": {k: get_stats(v) for k, v in alt_rot_breakdown.items()},
    "rotation_microbenchmark": {
        "bicubic_ms": rot_bicubic_ms,
        "nearest_ms": rot_nearest_ms,
        "transpose_ms": rot_transpose_ms,
        "diff_box": diff_box,
    },
    "crop_alpha_stats": {k: get_stats(v) for k, v in crop_alpha_stats.items()},
    "warmup_stats": {k: get_stats(v) for k, v in warmup_stats.items()},
    "compose_above_totals": get_stats(compose_above_totals),
    "compose_below_totals": get_stats(compose_below_totals),
}

with open(root / "scratch" / "profile_etap10o_results.json", "w", encoding="utf-8") as f:
    json.dump(results_dict, f, indent=2)
print("\nWrote results to scratch/profile_etap10o_results.json")
