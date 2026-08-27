import sys
import json
import math
import numpy as np
from pathlib import Path
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.gui.telemetry_manager import TelemetryDataManager
from src.indicators.moving_map import (
    render_map_working_image,
    render_map_unrotated_working_image,
    build_static_map_marker_tile,
    _map_render_plan,
)
from src.indicators.helpers import s, apply_map_shape, _parse_marker_color
from src.moving_map import track_up_rotation_degrees, track_up_working_size

PRESET = Path("presets/cycling_dashboard_v10.json")
VIDEO = Path("Video/GX010115.MP4")
FIT = Path("Video/Jazda_na_rowerze_w_porze_lunchu.fit")

with open(PRESET, "r", encoding="utf-8") as f:
    layout = json.load(f)

telemetry = TelemetryDataManager()
telemetry.load_gpmf_from_exiftool(VIDEO)
telemetry.load_fit(VIDEO, telemetry.start_dt_utc, manual_path=FIT)
gps_track = telemetry.get_gps_track_for_source("fit")
fit_data = telemetry.fit_data

def test_frame_parity(f_idx, heading_val):
    canvas_w, canvas_h = 3840, 2160
    cfg = layout["indicators"]["track_map"]
    map_w = s(cfg.get("size", 0.1), canvas_w)
    render_plan = _map_render_plan(canvas_w, map_w, int(cfg.get("zoom", 16)))
    marker_radius = max(1, int(round(float(cfg.get("marker_size", 7)) * (2.0 ** render_plan["zoom_offset"]))))
    marker_style = str(cfg.get("map_marker_style", "dot")).strip().lower()
    marker_color = _parse_marker_color(cfg.get("marker_color", "#FFFFFF"))
    
    # 1. CPU Reference
    cpu_img, cpu_dst = render_map_working_image(
        canvas_w, canvas_h, layout, "track_map",
        gps_track, current_position=(f_idx / 1131.0),
        map_heading=heading_val,
    )
    
    # 2. GPU Unrotated + Simulation
    angle = track_up_rotation_degrees(heading_val)
    if angle == 0.0:
        # Direct North-up path
        sim_img, _ = render_map_working_image(
            canvas_w, canvas_h, layout, "track_map",
            gps_track, current_position=(f_idx / 1131.0),
            map_heading=None,
        )
    else:
        unrotated_img, map_h, map_dst, working_size = render_map_unrotated_working_image(
            canvas_w, canvas_h, layout, "track_map",
            gps_track, current_position=(f_idx / 1131.0),
            map_heading=heading_val,
        )
        rot_pil = unrotated_img.rotate(float(heading_val or 0.0), resample=Image.BICUBIC, center=(working_size / 2.0, working_size / 2.0))
        offset = (working_size - map_w) // 2
        crop_pil = rot_pil.crop((offset, offset, offset + map_w, offset + map_w))
        if marker_style == "directional" and heading_val is not None:
            mkr_tile, mkr_rect = build_static_map_marker_tile(map_w, marker_radius, marker_style, marker_color)
            if mkr_tile is not None:
                crop_pil.paste(mkr_tile, (mkr_rect[0], mkr_rect[1]), mkr_tile)
        sim_img = apply_map_shape(crop_pil, cfg.get("map_shape", "square"))
        
    arr_cpu = np.array(cpu_img, dtype=np.float32)
    arr_sim = np.array(sim_img, dtype=np.float32)
    diff = np.abs(arr_cpu - arr_sim)
    max_d = np.max(diff)
    mae = np.mean(diff)
    
    print(f"Frame {f_idx:3d} (heading={str(heading_val):>5}): Max Diff={max_d:.1f}, MAE={mae:.4f}")

if __name__ == "__main__":
    print("Testing software parity:")
    test_frame_parity(0, None)
    test_frame_parity(10, 45.0)
    test_frame_parity(30, 90.0)
    test_frame_parity(60, 180.0)
    test_frame_parity(120, 270.0)
