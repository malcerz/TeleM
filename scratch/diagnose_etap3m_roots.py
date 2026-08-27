import json
import os
import sys
from pathlib import Path
from PIL import Image
import numpy as np

repo_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(repo_root))

from src.gui.telemetry_manager import TelemetryDataManager
from src.telemetry_processed_cache import read_processed_cache, apply_processed_cache
from src.indicators.compositor import compose_overlay
from src.indicators.frame_data import prepare_overlay_frame_data, build_active_fit_field_plan
from src.ffmpeg.amd_native_exporter import (
    _ordered_map_layout_parts,
    _cluster_above_bboxes_members,
    _extract_exact_above_regions,
)

VIDEO = repo_root / "Video" / "GX030120.MP4"
FIT = repo_root / "Video" / "Jazda_na_rowerze_w_porze_lunchu.fit"
LAYOUT_PATH = repo_root / "def_layout.json"

tm = TelemetryDataManager()
processed = read_processed_cache(VIDEO)
if processed is not None:
    apply_processed_cache(tm, processed)
else:
    tm.load_gpmf_from_exiftool(VIDEO)
tm.load_fit(VIDEO, start_dt=tm.start_dt_utc, manual_path=FIT)

layout = json.load(open(LAYOUT_PATH, encoding="utf-8"))
fit_field_plan = build_active_fit_field_plan(layout, (tm.fit_data or {}).keys())

from datetime import timedelta
fps = 30000.0 / 1001.0
target_dt = tm.start_dt_utc + timedelta(seconds=150 / fps) if tm.start_dt_utc else None

frame_kwargs = prepare_overlay_frame_data(
    layout=layout,
    target_dt=target_dt,
    tz_offset_hours=2,
    start_dt_utc=tm.start_dt_utc,
    speed_samples=tm.speed_samples,
    track_samples=tm.track_samples,
    alt_samples=tm.alt_samples,
    iso_samples=tm.iso_samples,
    exposure_samples=tm.exposure_samples,
    temperature_samples=tm.temperature_samples,
    fit_data=tm.fit_data,
    gps_track=tm.get_gps_track_for_source(
        layout.get("indicators", {}).get("track_map", {}).get("source", "fit")
    ),
    fit_field_plan=fit_field_plan,
)

# Split layout
compose_layout, map_above_layout, map_after_keys = _ordered_map_layout_parts(layout)

print("=" * 80)
print("1. MAP LAYOUT PARTS CHECK:")
print(f"  compose_layout indicators: {list(compose_layout.get('indicators', {}).keys())}")
print(f"  map_above_layout indicators: {list(map_above_layout.get('indicators', {}).keys())}")
print(f"  map_after_keys: {map_after_keys}")

# Check moving map render
from src.indicators.moving_map import render_map_working_image, render_map_unrotated_working_image

gpu_map_rotate_flag = True
if gpu_map_rotate_flag:
    map_img, map_heading_val, map_dst, working_size = render_map_unrotated_working_image(
        3840, 2160, layout, "track_map",
        frame_kwargs.get("gps_track"), target_dt=target_dt,
        current_position=frame_kwargs.get("current_position"),
        map_heading=frame_kwargs.get("map_heading"),
    )
    print(f"  GPU Map unrotated: img={map_img.size if map_img else None}, heading={map_heading_val}, dst={map_dst}")
    if map_img:
        map_img.save(repo_root / "scratch" / "debug_map_unrotated.png")

# 2. LEAN GPU CHECK
from src.indicators.lean import _load_lean_rotation_source, get_lean_gpu_transform_info
lean_src_img, lean_pivot = _load_lean_rotation_source(3840, 2160, layout.get("indicators", {}).get("lean_indicator", {}), 1080)
print(f"  Lean source sprite: size={lean_src_img.size if lean_src_img else None}, pivot={lean_pivot}")
if lean_src_img:
    lean_src_img.save(repo_root / "scratch" / "debug_lean_sprite.png")

# Check lean in compose_overlay
above_bboxes = {}
above_tight_bboxes = {}
above_full = compose_overlay(
    canvas_w=3840, canvas_h=2160, layout=map_above_layout, font_path="arial.ttf",
    _bboxes=above_bboxes, _tight_bboxes=above_tight_bboxes,
    gpu_capture_keys={"fit_cadence_text", "fit_heart_rate_text", "speed_text"},
    gpu_capture={}, reuse_canvas=False,
    **frame_kwargs
)
above_full.save(repo_root / "scratch" / "debug_above_full.png")
print(f"  above_full bboxes: {above_bboxes}")

# 3. Check BAR indicators in map_above_layout
print("  BAR indicators in above_bboxes:")
for k in ("fit_distance_text", "alt_text"):
    print(f"    {k}: bbox={above_bboxes.get(k)}, tight={above_tight_bboxes.get(k)}")

# Compare ref vs above_full for BAR
ref_img = Image.open(repo_root / "scratch" / "reference_frame_150.png")
for k in ("fit_distance_text", "alt_text"):
    bb = above_bboxes.get(k)
    if bb:
        x, y, w, h = bb
        c_ref = ref_img.crop((x, y, x + w, y + h))
        c_above = above_full.crop((x, y, x + w, y + h))
        c_ref.save(repo_root / "scratch" / f"debug_ref_{k}.png")
        c_above.save(repo_root / "scratch" / f"debug_above_{k}.png")
        diff = np.max(np.abs(np.array(c_ref).astype(int) - np.array(c_above).astype(int)))
        print(f"    {k} max diff between ref and above_full: {diff}")
