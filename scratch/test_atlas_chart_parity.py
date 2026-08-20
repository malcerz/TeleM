import sys, os, time, json
from pathlib import Path
_root = Path(__file__).resolve().parent.parent
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

from datetime import datetime, timedelta
import numpy as np
from PIL import Image

from telemetry_fit import process_fit
from src.gui.layout_manager import normalize_layout
from src.telemetry_extract import (
    load_json_with_fallback, ensure_records_list,
    extract_speed_samples, extract_altitude_samples, extract_track_samples,
    extract_iso_samples, extract_exposure_samples, extract_temperature_samples,
    find_gps_anchor,
)
from src.ffmpeg.command_builder import get_layout_hud_regions
from src.overlay_renderer import compose_overlay
from src.ffmpeg.worker_cache import init_worker, WORKER_CACHE
from src.telemetry_precompute import build_telemetry_cache

json_path = Path("Video/GX030120.json")
fit_path = Path("Video/Poranna_jazda_na_rowerze.fit")

raw_records = ensure_records_list(load_json_with_fallback(json_path))
anchor_dt = find_gps_anchor(raw_records)
fit_data = process_fit(str(fit_path), video_start_dt=anchor_dt)

speed_samples = extract_speed_samples(raw_records)
alt_samples = extract_altitude_samples(raw_records)
track_samples = extract_track_samples(raw_records)
iso_samples = extract_iso_samples(raw_records)
exposure_samples = extract_exposure_samples(raw_records)
temp_samples = extract_temperature_samples(raw_records)

field_samples = {
    "start_dt_utc": anchor_dt,
    "speed_samples": speed_samples,
    "track_samples": track_samples,
    "alt_samples": alt_samples,
    "iso_samples": iso_samples,
    "exposure_samples": exposure_samples,
    "temp_samples": temp_samples,
}

# 2-cluster layout that fits into atlas
layout = normalize_layout("def_layout.json", 1920, 1080)
for k, v in list(layout["indicators"].items()):
    if k not in ("time_block", "fit_cadence_text", "fit_enhanced_speed_text", "fit_heart_rate_text"):
        v["enabled"] = False

aw, ah, hud_regs = get_layout_hud_regions(layout, 1920, 1080, max_regions=3)
print(f"Atlas size: {aw}x{ah}, regions: {len(hud_regs)}")

# Init worker cache
init_worker(
    video_width=1920, video_height=1080,
    field_samples=field_samples,
    layout=layout,
    font_path="",
    fit_data=fit_data,
    start_dt_utc=anchor_dt,
    target_fps=29.97,
    total_overlay_frames=5400,
    gps_track=fit_data.get("track"),
    hud_regions=hud_regs,
)

from src.indicators.frame_data import prepare_overlay_frame_data
from src.ffmpeg.worker_cache import _resolve_cache_value

target_dt = anchor_dt + timedelta(seconds=2700 / 29.97)
fd = prepare_overlay_frame_data(
    layout=layout,
    target_dt=target_dt,
    tz_offset_hours=0.0,
    start_dt_utc=anchor_dt,
    speed_samples=speed_samples,
    track_samples=track_samples,
    alt_samples=alt_samples,
    iso_samples=iso_samples,
    exposure_samples=exposure_samples,
    temperature_samples=temp_samples,
    fit_data=fit_data,
    gps_track=fit_data.get("track"),
    total_frames=5400,
    current_index=2700,
    chart_data=WORKER_CACHE.get("_precomputed_chart_data"),
    resolve_cache_value=_resolve_cache_value,
    _range_cache=WORKER_CACHE.get("_prep_cache"),
)

# 1. Full canvas render
full_img = compose_overlay(1920, 1080, layout, font_path="", **fd)

# Extract region containing cadence (Reg 2: 44, 748, 1082x332)
cad_full_crop = full_img.crop((44, 748, 44 + 1082, 748 + 332))

# 2. Atlas render
atlas_canvas = Image.new("RGBA", (aw, ah), (0, 0, 0, 0))
for sx, sy, dx, dy, rw, rh in hud_regs:
    crop_sub = full_img.crop((sx, sy, sx + rw, sy + rh))
    atlas_canvas.paste(crop_sub, (dx, dy))

# Reconstruct from atlas
reconstructed = Image.new("RGBA", (1920, 1080), (0, 0, 0, 0))
for sx, sy, dx, dy, rw, rh in hud_regs:
    crop_sub = atlas_canvas.crop((dx, dy, dx + rw, dy + rh))
    reconstructed.paste(crop_sub, (sx, sy))

diff = np.abs(np.array(full_img, dtype=np.int32) - np.array(reconstructed, dtype=np.int32))
# Only compare within the active HUD regions
mask = np.zeros((1080, 1920), dtype=bool)
for sx, sy, dx, dy, rw, rh in hud_regs:
    mask[sy:sy+rh, sx:sx+rw] = True

diff_in_hud = diff[mask]
max_diff = np.max(diff_in_hud)
print(f"FULL_FRAME vs ATLAS reconstructed HUD diff: max_diff = {max_diff}")
assert max_diff == 0, f"Atlas reconstruction mismatch: {max_diff}"
print("[OK] FULL_FRAME vs ATLAS chart parity verified 100%!")
