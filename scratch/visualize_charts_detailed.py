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
from src.indicators.chart_builder import build_chart_data, clip_chart_data
from src.overlay_renderer import compose_overlay
from src.ffmpeg.worker_cache import init_worker, WORKER_CACHE, _resolve_cache_value
from src.indicators.frame_data import prepare_overlay_frame_data

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

layout = normalize_layout("def_layout.json", 1920, 1080)

# Initialize worker cache
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
)

out_dir = Path("scratch/visual_charts")
out_dir.mkdir(parents=True, exist_ok=True)

for f_idx in [0, 500, 1500, 2700, 4000, 5399]:
    target_dt = anchor_dt + timedelta(seconds=f_idx / 29.97)
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
        current_index=f_idx,
        chart_data=WORKER_CACHE.get("_precomputed_chart_data"),
        resolve_cache_value=_resolve_cache_value,
        _range_cache=WORKER_CACHE.get("_prep_cache"),
    )

    img = compose_overlay(
        1920, 1080, layout, font_path="",
        **fd
    )
    img.save(out_dir / f"full_frame_{f_idx}.png")
    
    # Crop Cadence area (x~0..700, y~700..1080)
    cad_crop = img.crop((0, 700, 750, 1080))
    cad_crop.save(out_dir / f"cadence_crop_f{f_idx}.png")
    
    # Crop HR area (x~1150..1920, y~700..1080)
    hr_crop = img.crop((1150, 700, 1920, 1080))
    hr_crop.save(out_dir / f"hr_crop_f{f_idx}.png")

print("Saved detailed visual crops to scratch/visual_charts/")
