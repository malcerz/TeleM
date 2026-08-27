import os
import sys
import time
import json
from pathlib import Path
from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.gui.telemetry_manager import TelemetryDataManager
from src.indicators.moving_map import _map_render_plan, _shared_map_renderers, ensure_map_tiles_cached
from src.indicators.helpers import s, apply_map_shape, _parse_marker_color
from src.moving_map import (
    MovingMapRenderer,
    set_map_network_allowed,
    reset_map_tile_stats,
    get_map_tile_stats,
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
    # fallback to default track_map settings
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

info = ensure_map_tiles_cached(canvas_w, canvas_h, layout, "track_map", gps_track)
print(f"Preload info: {info}")

set_map_network_allowed(False)
reset_map_tile_stats()

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

# Warm up 5 frames
for i in range(5):
    ts = (i / 1131.0) * dur
    renderer.render_track_up(ts, working_size, heading=45.0)

timings = {
    "position_interp": [],
    "tile_assembly_cache": [],
    "route_raster": [],
    "working_canvas_crop": [],
    "pillow_rotate": [],
    "crop_final": [],
    "marker": [],
    "map_shape": [],
    "tobytes": [],
    "other": [],
    "total": [],
}

num_frames = 300
for f_idx in range(num_frames):
    t_start = time.perf_counter()
    ts = (f_idx / 1131.0) * dur
    map_heading = (45.0 + f_idx * 0.2) % 360.0

    # 1. Position / interpolation
    t0 = time.perf_counter()
    cpx, cpy = renderer._interp_pos(ts)
    t1 = time.perf_counter()
    timings["position_interp"].append((t1 - t0) * 1000.0)

    # 2. Tile assembly / grid check
    working = working_size
    output_size = working_size
    margin = 1
    half_w = int(working / 2 / TILE_SIZE) + 1 + margin
    half_h = int(working / 2 / TILE_SIZE) + 1 + margin
    cx, cy = int(cpx / TILE_SIZE), int(cpy / TILE_SIZE)
    tx1, tx2 = cx - half_w, cx + half_w + 1
    ty1, ty2 = cy - half_h, cy + half_h + 1

    t2 = time.perf_counter()
    grid_key = (tx1, tx2, ty1, ty2, renderer._zoom, renderer._style, True,
                renderer._trk_color, renderer._trk_width,
                renderer._track_aa, renderer._track_outline_w, renderer._track_outline_color)
    
    route_time = 0.0
    if getattr(renderer, "_grid_cache_key", None) == grid_key and hasattr(renderer, "_grid_cache_img"):
        img = renderer._grid_cache_img
    else:
        tw = (tx2 - tx1) * TILE_SIZE
        th = (ty2 - ty1) * TILE_SIZE
        img = Image.new("RGBA", (tw, th), (30, 30, 30, 255))
        for ty in range(ty1, ty2):
            for tx in range(tx1, tx2):
                tile = renderer._cache.get(renderer._zoom, tx, ty, renderer._style)
                if tile:
                    dx, dy = (tx - tx1) * TILE_SIZE, (ty - ty1) * TILE_SIZE
                    img.paste(tile, (dx, dy))
        # Route raster
        t_r0 = time.perf_counter()
        ox, oy = tx1 * TILE_SIZE, ty1 * TILE_SIZE
        pts = [(renderer._px_x[i] - ox, renderer._px_y[i] - oy) for i in range(len(renderer._gps))]
        d_grid = ImageDraw.Draw(img)
        d_grid.line(pts, fill=renderer._trk_color, width=max(1, renderer._trk_width), joint="round")
        t_r1 = time.perf_counter()
        route_time = (t_r1 - t_r0) * 1000.0
        renderer._grid_cache_key = grid_key
        renderer._grid_cache_img = img
    t3 = time.perf_counter()
    timings["tile_assembly_cache"].append((t3 - t2 - (route_time / 1000.0)) * 1000.0)
    timings["route_raster"].append(route_time)

    # 3. Working canvas crop (978x978 unrotated from grid)
    t4 = time.perf_counter()
    tw = (tx2 - tx1) * TILE_SIZE
    th = (ty2 - ty1) * TILE_SIZE
    scx, scy = cpx - tx1 * TILE_SIZE, cpy - ty1 * TILE_SIZE
    x1 = max(0, int(scx - working / 2))
    y1 = max(0, int(scy - working / 2))
    x2, y2 = x1 + working, y1 + working
    if x2 > tw: x2 = tw; x1 = max(0, x2 - working)
    if y2 > th: y2 = th; y1 = max(0, y2 - working)
    cropped_working = img.crop((x1, y1, x2, y2))
    t5 = time.perf_counter()
    timings["working_canvas_crop"].append((t5 - t4) * 1000.0)

    # 4. Pillow BICUBIC rotate
    t6 = time.perf_counter()
    rot_angle = track_up_rotation_degrees(map_heading)
    rot = cropped_working.rotate(
        rot_angle,
        resample=getattr(Image, "Resampling", Image).BICUBIC,
        center=(working / 2, working / 2),
    )
    t7 = time.perf_counter()
    timings["pillow_rotate"].append((t7 - t6) * 1000.0)

    # 5. Crop final (691x691 from rotated 978x978)
    t8 = time.perf_counter()
    cw, ch = rot.size
    final_size = s(cfg.get("size", 0.1), canvas_w)
    cx_f, cy_f = cw / 2, ch / 2
    final_crop = rot.crop((
        int(cx_f - final_size / 2),
        int(cy_f - final_size / 2),
        int(cx_f - final_size / 2) + final_size,
        int(cy_f - final_size / 2) + final_size,
    ))
    t9 = time.perf_counter()
    timings["crop_final"].append((t9 - t8) * 1000.0)

    # 6. Marker (directional upright marker)
    t10 = time.perf_counter()
    d_mkr = ImageDraw.Draw(final_crop)
    mx, my = final_size / 2, final_size / 2
    r = renderer._mkr_radius
    d_mkr.ellipse(
        [mx - r, my - r, mx + r, my + r],
        fill=(255, 255, 255, 255),
        outline=(0, 0, 0, 220),
        width=2,
    )
    t11 = time.perf_counter()
    timings["marker"].append((t11 - t10) * 1000.0)

    # 7. Map shape
    t12 = time.perf_counter()
    shaped = apply_map_shape(final_crop, cfg.get("map_shape", "square"))
    t13 = time.perf_counter()
    timings["map_shape"].append((t13 - t12) * 1000.0)

    # 8. tobytes
    t14 = time.perf_counter()
    raw_b = shaped.tobytes("raw", "RGBA")
    t15 = time.perf_counter()
    timings["tobytes"].append((t15 - t14) * 1000.0)

    t_end = time.perf_counter()
    total_ms = (t_end - t_start) * 1000.0
    accounted_ms = sum(timings[k][-1] for k in timings if k not in ("other", "total"))
    timings["other"].append(max(0.0, total_ms - accounted_ms))
    timings["total"].append(total_ms)

print("\n" + "=" * 80)
print(f"CPU MAP BREAKDOWN (300 FRAMES 4K / WARM CACHE)")
print("=" * 80)
print(f"{'Stage':<25} {'AVG ms':>10} {'Median':>10} {'P95':>10} {'Min':>10} {'Max':>10} {'Share %':>10}")
print("-" * 80)
for k, vals in timings.items():
    if not vals: continue
    s_vals = sorted(vals)
    avg = sum(vals) / len(vals)
    med = s_vals[len(s_vals) // 2]
    p95 = s_vals[int(len(s_vals) * 0.95)]
    mn = min(vals)
    mx = max(vals)
    share = (avg / (sum(timings["total"]) / len(timings["total"]))) * 100.0 if k != "total" else 100.0
    print(f"{k:<25} {avg:>10.3f} {med:>10.3f} {p95:>10.3f} {mn:>10.3f} {mx:>10.3f} {share:>9.1f}%")

print("=" * 80)
