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
from src.indicators.chart import _render_chart_indicator
from src.overlay_renderer import compose_overlay
from src.ffmpeg.worker_cache import init_worker, WORKER_CACHE

# Load GX030120 data
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

chart_data = WORKER_CACHE["_precomputed_chart_data"]
print("Precomputed chart data keys in WORKER_CACHE:")
for k, v in chart_data.items():
    print(f"  {k:25s}: {len(v)} points, scope={getattr(v, 'time_scope', None)}, start={getattr(v, 'chart_start_dt', None)}, end={getattr(v, 'chart_end_dt', None)}")

out_dir = Path("scratch/chart_inspect")
out_dir.mkdir(parents=True, exist_ok=True)

# Test rendering direct chart indicators
for f_idx in [0, 500, 1000, 2700, 5399]:
    target_dt = anchor_dt + timedelta(seconds=f_idx / 29.97)
    
    # 1. Cadence chart
    cad_cfg = layout["indicators"]["fit_cadence_text"]
    cad_history = chart_data.get("fit_cadence_text")
    cad_val = fit_data["cadence"][min(f_idx, len(fit_data["cadence"])-1)][1] if "cadence" in fit_data else 0
    
    cad_res = _render_chart_indicator(
        canvas_w=1920, canvas_h=1080, layout=layout, font_path="",
        key="fit_cadence_text", value=cad_val, unit="rpm", label="CADENCE",
        cfg=cad_cfg, min_dim=1080, outline=2, fs=20, font=None,
        val_min=0, val_max=120, ticks=4, thickness=2, size_px=int(cad_cfg.get("size", 200)), ss=1,
        history_data=cad_history, current_position=f_idx / 5399,
        target_dt=target_dt,
    )
    cad_img = cad_res[0]
    if hasattr(cad_img, "static"):  # ChartSplit
        cad_img.static.save(out_dir / f"cadence_static_f{f_idx}.png")
    else:
        cad_img.save(out_dir / f"cadence_f{f_idx}.png")

    # 2. Heart rate chart
    hr_cfg = layout["indicators"]["fit_heart_rate_text"]
    hr_history = chart_data.get("fit_heart_rate_text")
    hr_val = fit_data["heart_rate"][min(f_idx, len(fit_data["heart_rate"])-1)][1] if "heart_rate" in fit_data else 0
    
    hr_res = _render_chart_indicator(
        canvas_w=1920, canvas_h=1080, layout=layout, font_path="",
        key="fit_heart_rate_text", value=hr_val, unit="BPM", label="HEART RATE",
        cfg=hr_cfg, min_dim=1080, outline=2, fs=20, font=None,
        val_min=40, val_max=200, ticks=4, thickness=2, size_px=int(hr_cfg.get("size", 200)), ss=1,
        history_data=hr_history, current_position=f_idx / 5399,
        target_dt=target_dt,
    )
    hr_img = hr_res[0]
    if hasattr(hr_img, "static"):
        hr_img.static.save(out_dir / f"hr_static_f{f_idx}.png")
    else:
        hr_img.save(out_dir / f"hr_f{f_idx}.png")

print("Saved chart images to scratch/chart_inspect/")
