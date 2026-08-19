"""Diagnostic script to compare all 5 gauge stages and find where arc/ticks diverge."""
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from PIL import Image
import numpy as np

root = Path("c:/_DEV/TeleM")
sys.path.insert(0, str(root))
sys.path.insert(0, str(root / "src"))

from src.gui.telemetry_manager import TelemetryDataManager
from src.telemetry_extract import (
    ensure_records_list, load_json_with_fallback,
    extract_speed_samples, extract_altitude_samples, extract_track_samples,
    extract_iso_samples, extract_exposure_samples, extract_temperature_samples,
    smooth_speed_samples, interpolate_value, get_rotation_from_metadata,
    get_container_rotation, find_metadata_json, extract_gps_track,
    smooth_speed_values, extract_accelerometer_samples, extract_gyroscope_samples,
)
from src.indicators.chart_builder import build_chart_data
from src.indicators.frame_data import prepare_overlay_frame_data
from src.indicators.compositor import compose_overlay
from src.indicators.dispatcher import render_value_indicator
from src.indicators.gauge import _render_gauge_indicator
from src.gui.layout_manager import normalize_layout

out_dir = root / "Raporty" / "etap8m5_artifacts"
out_dir.mkdir(parents=True, exist_ok=True)

# 1. Load layout and telemetry
layout = normalize_layout(root / "def_layout.json", 1920, 1080)
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

records = ensure_records_list(load_json_with_fallback(root / "Video" / "GX020079.json"))
telemetry.load_gpmf_records(records)
telemetry.load_fit(str(root / "Video" / "Morning_Ride.fit"))

target_dt = telemetry.start_dt_utc + timedelta(seconds=18.87)

# Prepare frame data
chart_data = build_chart_data(
    layout, telemetry.get_samples_for_source, telemetry.resolve_samples,
    start_dt_utc=telemetry.start_dt_utc, end_dt_utc=telemetry.start_dt_utc + timedelta(seconds=37.74),
)
frame_data = prepare_overlay_frame_data(
    layout=layout,
    target_dt=target_dt,
    tz_offset_hours=2,
    start_dt_utc=telemetry.start_dt_utc,
    speed_samples=telemetry.speed_samples or [],
    track_samples=telemetry.track_samples or [],
    alt_samples=telemetry.alt_samples or [],
    iso_samples=telemetry.iso_samples,
    exposure_samples=telemetry.exposure_samples,
    temperature_samples=telemetry.temperature_samples,
    fit_data=telemetry.fit_data,
    chart_data=chart_data,
    resolve_cache_value=lambda field, src, dt, key=None: telemetry.resolve_value(field, dt, source=src, indicator_key=key),
)

gauge_key = "fit_enhanced_speed_text"
gauge_cfg = layout["indicators"][gauge_key]
print(f"Gauge key: {gauge_key}")
print(f"Gauge cfg: {gauge_cfg}")

# STAGE 1: Preview gauge (rendered on full Pillow HUD canvas)
preview_bboxes = {}
preview_canvas = compose_overlay(
    canvas_w=1920, canvas_h=1080,
    layout=layout, font_path="assets/Roboto-Bold.ttf",
    _bboxes=preview_bboxes,
    gpu_capture_keys=None,
    reuse_canvas=False,
    **frame_data,
)
print(f"frame_data extra_indicators: {frame_data.get('extra_indicators', {})}")
print(f"frame_data indicator_values: {frame_data.get('indicator_values', {})}")
print(f"preview_bboxes keys: {list(preview_bboxes.keys())}")
if gauge_key not in preview_bboxes:
    print(f"ERROR: {gauge_key} not in preview_bboxes!")
    sys.exit(1)
g_bbox = preview_bboxes[gauge_key]
print(f"Preview gauge bbox: {g_bbox}")
x, y, w, h = g_bbox
stage1_crop = preview_canvas.crop((x, y, x + w, y + h))
stage1_crop.save(out_dir / "01_preview_gauge.png")

# STAGE 2: CPU gauge raw (direct call to render_value_indicator)
stage2_img, cx, cy, _ = render_value_indicator(
    canvas_w=1920, canvas_h=1080,
    layout=layout, font_path="assets/Roboto-Bold.ttf",
    key=gauge_key, value=frame_data["extra_indicators"].get(gauge_key, (25.0,))[0],
    unit="km/h", label="Speed", cfg_override=gauge_cfg,
    target_dt=target_dt,
)
stage2_img.save(out_dir / "02_cpu_gauge_raw.png")

# STAGE 3: GPU capture source (captured during compositor run with gpu_capture_keys)
gpu_capture = {}
gpu_bboxes = {}
capture_canvas = compose_overlay(
    canvas_w=1920, canvas_h=1080,
    layout=layout, font_path="assets/Roboto-Bold.ttf",
    _bboxes=gpu_bboxes,
    gpu_capture_keys={gauge_key},
    gpu_capture=gpu_capture,
    reuse_canvas=False,
    **frame_data,
)
stage3_cap = gpu_capture.get(gauge_key)
stage3_img = stage3_cap["image"]
stage3_bbox = stage3_cap["bbox"]
print(f"GPU capture bbox: {stage3_bbox}, image size: {stage3_img.size}")
stage3_img.save(out_dir / "03_gpu_capture_source.png")

# STAGE 4: GPU uploaded texture (clipped to HUD bounds as done in amd_native_exporter.py)
gx, gy, gw, gh = stage3_bbox
cx0, cy0 = max(0, gx), max(0, gy)
cx1, cy1 = min(1920, gx + gw), min(1080, gy + gh)
stage4_img = stage3_img.crop((cx0 - gx, cy0 - gy, cx1 - gx, cy1 - gy))
stage4_img.save(out_dir / "04_gpu_uploaded_texture.png")
print(f"GPU upload texture size: {stage4_img.size}, dst rect: ({cx0}, {cy0}, {cx1-cx0}, {cy1-cy0})")

# Let's inspect Alpha / White pixels in each stage:
for name, img in [
    ("Stage 1 (Preview crop)", stage1_crop),
    ("Stage 2 (CPU raw)", stage2_img),
    ("Stage 3 (GPU capture source)", stage3_img),
    ("Stage 4 (GPU upload texture)", stage4_img),
]:
    arr = np.array(img)
    alpha = arr[:, :, 3]
    rgb = arr[:, :, :3]
    non_zero = np.count_nonzero(alpha > 0)
    # White / near white tick pixels (R>200, G>200, B>200, A>200)
    white_mask = (alpha > 200) & (rgb[:, :, 0] > 200) & (rgb[:, :, 1] > 200) & (rgb[:, :, 2] > 200)
    white_px = np.count_nonzero(white_mask)
    print(f"[{name}] size={img.size} non_zero_alpha={non_zero} white_pixels={white_px}")
