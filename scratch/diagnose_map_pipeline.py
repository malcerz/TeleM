"""Diagnose map pipeline and generate artifacts 01 through 05."""
import json
import sys
import os
import ctypes
from pathlib import Path
from PIL import Image
import numpy as np

root = Path("c:/_DEV/TeleM")
sys.path.insert(0, str(root))
sys.path.insert(0, str(root / "src"))

from src.gui.telemetry_manager import TelemetryDataManager
from src.telemetry_extract import (
    ensure_records_list, extract_altitude_samples, extract_exposure_samples,
    extract_iso_samples, extract_speed_samples, extract_temperature_samples,
    extract_track_samples, interpolate_value, load_json_with_fallback,
    smooth_speed_samples
)
from src.indicators.moving_map import render_map_working_image, _map_render_plan, apply_map_shape
from src.indicators.helpers import s

def run_diagnostics():
    fit_path = root / "Video" / "Popoludniowa_jazda_na_rowerze_solar_battery.fit"
    json_path = root / "Video" / "GX030120.json"
    records = ensure_records_list(load_json_with_fallback(json_path))
    tm = TelemetryDataManager(
        extract_speed_samples, extract_altitude_samples, extract_track_samples,
        extract_iso_samples, extract_exposure_samples, extract_temperature_samples,
        smooth_speed_samples, interpolate_value
    )
    tm.load_gpmf_records(records)
    tm.load_fit(fit_path)
    tm.start_dt_utc = tm.speed_samples[0][0]

    layout = json.load(open(root / "def_layout.json", encoding="utf-8"))
    gps_track = tm.get_gps_track_for_source("fit")
    
    cfg = layout["indicators"]["track_map"]
    canvas_w, canvas_h = 3840, 2160
    map_w = s(cfg.get("size", 0.1), canvas_w)
    render_plan = _map_render_plan(canvas_w, map_w, int(cfg.get("zoom", 16)))
    working_size = render_plan["working_size"]
    effective_zoom = render_plan["effective_zoom"]
    map_style = cfg.get("map_style", "light_all")
    
    from src.moving_map import MovingMapRenderer
    renderer = MovingMapRenderer(
        gps_track, zoom=effective_zoom, style=map_style,
        marker_color=(255, 255, 255),
        marker_radius=max(1, int(round(float(cfg.get("marker_size", 7)) * (2.0 ** render_plan["zoom_offset"])))),
        track_color=(255, 60, 30, 220),
        track_width=max(1, int(round(int(cfg.get("track_width", 3)) * (2.0 ** render_plan["zoom_offset"])))),
    )
    
    frame_idx = 30
    pts_s = frame_idx * (1001.0 / 30000.0)
    curr_dt = tm.start_dt_utc + (tm.speed_samples[-1][0] - tm.speed_samples[0][0]) * (pts_s / 180.0)
    
    gps0 = gps_track[0][0]
    import datetime
    from datetime import timezone
    target_epoch = curr_dt.timestamp() if curr_dt.tzinfo is not None else curr_dt.replace(tzinfo=timezone.utc).timestamp()
    gps0_ts = gps0.timestamp() if gps0.tzinfo is not None else gps0.replace(tzinfo=timezone.utc).timestamp()
    ts = target_epoch - gps0_ts
    
    # 01_map_renderer_raw.png: full working image from renderer.render
    raw_map = renderer.render(
        ts, working_size, working_size,
        download_missing=True,
        draw_track=True,
        draw_marker=True,
    )
    diag_dir = root / "scratch" / "etap8m_diag"
    diag_dir.mkdir(parents=True, exist_ok=True)
    raw_map.save(diag_dir / "01_map_renderer_raw.png")
    print(f"01_map_renderer_raw: size={raw_map.size}, mode={raw_map.mode}")
    
    # 02_map_after_crop.png / apply_map_shape
    after_shape = apply_map_shape(raw_map, cfg.get("map_shape", "square"))
    after_shape.save(diag_dir / "02_map_after_crop.png")
    print(f"02_map_after_crop: size={after_shape.size}, mode={after_shape.mode}")
    
    # 03_map_upload_source.png
    map_img, dst_bbox = render_map_working_image(
        canvas_w, canvas_h, layout, "track_map",
        gps_track, target_dt=curr_dt, current_position=0.0
    )
    map_img.save(diag_dir / "03_map_upload_source.png")
    print(f"03_map_upload_source: size={map_img.size}, mode={map_img.mode}, dst_bbox={dst_bbox}")

if __name__ == "__main__":
    run_diagnostics()
