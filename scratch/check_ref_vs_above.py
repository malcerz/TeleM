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
)
from datetime import timedelta

VIDEO = repo_root / "Video" / "GX030120.MP4"
FIT = repo_root / "Video" / "Jazda_na_rowerze_w_porze_lunchu.fit"
LAYOUT_PATH = repo_root / "def_layout.json"

tm = TelemetryDataManager()
processed = read_processed_cache(VIDEO)
if processed is not None:
    apply_processed_cache(tm, processed)
tm.load_fit(VIDEO, start_dt=tm.start_dt_utc, manual_path=FIT)
layout = json.load(open(LAYOUT_PATH, encoding="utf-8"))
fit_field_plan = build_active_fit_field_plan(layout, (tm.fit_data or {}).keys())

fps = 30000.0 / 1001.0
target_dt = tm.start_dt_utc + timedelta(seconds=150 / fps) if tm.start_dt_utc else None
gps_track = tm.get_gps_track_for_source(layout.get("indicators", {}).get("track_map", {}).get("source", "fit"))

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
    gps_track=gps_track,
    fit_field_plan=fit_field_plan,
)

# 1. Full CPU Reference Frame
ref_img = compose_overlay(
    canvas_w=3840, canvas_h=2160, layout=layout, font_path="arial.ttf",
    **frame_kwargs
)
ref_img.save(repo_root / "scratch" / "reference_frame_150.png")

# 2. CPU map_above_layout
compose_layout, map_above_layout, map_after_keys = _ordered_map_layout_parts(layout)

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

print("Checking differences between Reference and map_above_layout:")
for k in ("fit_distance_text", "alt_text", "lean_indicator"):
    bb = above_bboxes.get(k)
    tbb = above_tight_bboxes.get(k)
    print(f"  {k}: bbox={bb}, tight={tbb}")
    if bb:
        x, y, w, h = bb
        c_ref = ref_img.crop((x, y, x + w, y + h))
        c_above = above_full.crop((x, y, x + w, y + h))
        c_ref.save(repo_root / "scratch" / f"debug_ref_{k}.png")
        c_above.save(repo_root / "scratch" / f"debug_above_{k}.png")
        diff = np.max(np.abs(np.array(c_ref).astype(int) - np.array(c_above).astype(int)))
        print(f"    {k} max diff between ref and above_full: {diff}")
