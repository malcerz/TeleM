import os
import sys
import time
import json
import math
import numpy as np
from pathlib import Path
from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.gui.telemetry_manager import TelemetryDataManager
from src.indicators.moving_map import _map_render_plan, ensure_map_tiles_cached
from src.indicators.helpers import s, apply_map_shape, _parse_marker_color
from src.moving_map import (
    MovingMapRenderer,
    set_map_network_allowed,
    reset_map_tile_stats,
    track_up_working_size,
    track_up_rotation_degrees,
    TILE_SIZE,
)

PRESET = Path("presets/cycling_dashboard_v10.json")
VIDEO = Path("Video/GX010115.MP4")
FIT = Path("Video/Jazda_na_rowerze_w_porze_lunchu.fit")

with open(PRESET, "r", encoding="utf-8") as f:
    layout = json.load(f)

telemetry = TelemetryDataManager()
telemetry.load_gpmf_from_exiftool(VIDEO)
telemetry.load_fit(VIDEO, telemetry.start_dt_utc, manual_path=FIT)
gps_track = telemetry.get_gps_track_for_source("fit")

canvas_w, canvas_h = 3840, 2160
key = "track_map"
cfg = layout["indicators"].get(key, {})
if not cfg:
    cfg = {
        "enabled": True, "label": "Mapa", "x": 84.0, "y": 28.0, "rotation": 0, "form": "map",
        "font_size": 1.2, "size": 18.0, "thickness": 1, "zoom": 16,
        "source": "fit", "map_style": "satellite", "map_shape": "square",
        "map_orientation": "track_up", "map_marker_style": "directional",
        "marker_size": 7, "marker_color": "#FFFFFF", "track_color": "#FF3C1E",
        "track_width": 3, "track_antialiasing": 1, "track_outline_width": 0,
    }
    layout["indicators"]["track_map"] = cfg

map_w = s(cfg.get("size", 0.1), canvas_w)
render_plan = _map_render_plan(canvas_w, map_w, int(cfg.get("zoom", 16)))
working_size = render_plan["working_size"]
effective_zoom = render_plan["effective_zoom"]
map_style = cfg.get("map_style", "light_all")
marker_style = str(cfg.get("map_marker_style", "dot")).strip().lower()
track_color = _parse_marker_color(cfg.get("track_color", "#FF3C1E"))
if len(track_color) == 3:
    track_color = (*track_color, 220)
track_width = int(cfg.get("track_width", 3))
track_aa = max(1, min(8, int(cfg.get("track_antialiasing", 1) or 1)))
track_outline_w = max(0, int(cfg.get("track_outline_width", 0) or 0))
track_outline_color = _parse_marker_color(cfg.get("track_outline_color", "#000000"))

ensure_map_tiles_cached(canvas_w, canvas_h, layout, "track_map", gps_track)

renderer = MovingMapRenderer(
    gps_track, zoom=effective_zoom, style=map_style,
    marker_color=_parse_marker_color(cfg.get("marker_color", "#FFFFFF")),
    marker_radius=max(1, int(round(
        float(cfg.get("marker_size", 7)) * (2.0 ** render_plan["zoom_offset"])
    ))),
    track_color=track_color,
    track_width=max(1, int(round(
        track_width * (2.0 ** render_plan["zoom_offset"])
    ))),
    marker_style=marker_style,
    track_antialiasing=track_aa,
    track_outline_width=track_outline_w,
    track_outline_color=track_outline_color,
)

dur = (gps_track[-1][0].timestamp() - gps_track[0][0].timestamp())

def compare_frame(f_idx):
    ts = (f_idx / 1131.0) * dur
    map_heading = (45.0 + f_idx * 0.2) % 360.0
    
    # 1. CPU Reference
    ref_img = renderer.render_track_up(ts, map_w, heading=map_heading, draw_track=True, draw_marker=True, download_missing=False)
    ref_shaped = apply_map_shape(ref_img, cfg.get("map_shape", "square"))
    
    # 2. CPU Unrotated
    unrotated_working = renderer.render(ts, working_size, working_size, draw_track=True, draw_marker=False, download_missing=False, heading=None)
    
    # Check sizes
    print(f"Frame {f_idx}: CPU Ref size={ref_shaped.size}, Unrotated Working size={unrotated_working.size}, heading={map_heading:.1f}°")
    return ref_shaped, unrotated_working, map_heading

if __name__ == "__main__":
    for idx in [0, 10, 30, 60, 120, 240]:
        compare_frame(idx)
