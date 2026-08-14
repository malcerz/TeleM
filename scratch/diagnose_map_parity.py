"""Runtime evidence for AMD ETAP 5C-PRECHECK map Preview/Export parity.

This is a diagnostic runner only.  It does not execute or benchmark the map
optimizations planned for ETAP 5C.
"""

from __future__ import annotations

import json
import math
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.gui.telemetry_manager import TelemetryDataManager
from src.indicators.helpers import s
from src.indicators.moving_map import _map_render_plan
from src.moving_map import MovingMapRenderer, TILE_SIZE


FRAMES = (30, 300, 900)
CANVASES = ((960, 540), (1920, 1080), (3840, 2160))
START_DT = datetime(2026, 8, 5, 4, 28, 11)


def _epoch(value):
    return (
        value.timestamp()
        if value.tzinfo is not None
        else value.replace(tzinfo=timezone.utc).timestamp()
    )


def _world_to_geo(x: float, y: float, zoom: int) -> tuple[float, float]:
    world_size = TILE_SIZE * (2 ** zoom)
    lon = x / world_size * 360.0 - 180.0
    mercator = math.pi * (1.0 - 2.0 * y / world_size)
    lat = math.degrees(math.atan(math.sinh(mercator)))
    return lat, lon


def _geometry(renderer, ts: float, crop_size: int) -> dict:
    cpx, cpy = renderer._interp_pos(ts)
    cx, cy = int(cpx // TILE_SIZE), int(cpy // TILE_SIZE)
    half = int(math.ceil(crop_size / 2 / TILE_SIZE)) + 1
    tx1, tx2 = cx - half, cx + half + 1
    ty1, ty2 = cy - half, cy + half + 1
    grid_w = (tx2 - tx1) * TILE_SIZE
    grid_h = (ty2 - ty1) * TILE_SIZE
    marker_grid_x = cpx - tx1 * TILE_SIZE
    marker_grid_y = cpy - ty1 * TILE_SIZE
    crop_x = max(0, int(marker_grid_x - crop_size / 2))
    crop_y = max(0, int(marker_grid_y - crop_size / 2))
    crop_x = min(crop_x, grid_w - crop_size)
    crop_y = min(crop_y, grid_h - crop_size)
    world_x1 = tx1 * TILE_SIZE + crop_x
    world_y1 = ty1 * TILE_SIZE + crop_y
    world_x2 = world_x1 + crop_size
    world_y2 = world_y1 + crop_size
    max_lat, min_lon = _world_to_geo(world_x1, world_y1, renderer._zoom)
    min_lat, max_lon = _world_to_geo(world_x2, world_y2, renderer._zoom)
    return {
        "working_grid": [grid_w, grid_h],
        "tile_range": [tx1, tx2, ty1, ty2],
        "crop": [crop_x, crop_y, crop_size, crop_size],
        "marker_source": [cpx, cpy],
        "marker_grid": [marker_grid_x, marker_grid_y],
        "marker_local": [cpx - world_x1, cpy - world_y1],
        "marker_local_normalized": [
            (cpx - world_x1) / crop_size,
            (cpy - world_y1) / crop_size,
        ],
        "geographic_bounds": {
            "min_lat": min_lat,
            "max_lat": max_lat,
            "min_lon": min_lon,
            "max_lon": max_lon,
        },
    }


def _route_normalized(renderer, geometry: dict) -> list[tuple[float, float]]:
    tx1, _, ty1, _ = geometry["tile_range"]
    crop_x, crop_y, crop_w, crop_h = geometry["crop"]
    world_x1 = tx1 * TILE_SIZE + crop_x
    world_y1 = ty1 * TILE_SIZE + crop_y
    return [
        ((x - world_x1) / crop_w, (y - world_y1) / crop_h)
        for x, y in zip(renderer._px_x, renderer._px_y)
    ]


def main() -> int:
    out_dir = ROOT / "Raporty" / "AMD_ETAP5C_PRECHECK"
    out_dir.mkdir(parents=True, exist_ok=True)
    layout = json.loads((ROOT / "def_layout.json").read_text(encoding="utf-8"))
    cfg = layout["indicators"]["track_map"]
    telemetry = TelemetryDataManager()
    telemetry.load_fit(ROOT / "Video" / "Morning_Ride.fit")
    gps_track = telemetry.get_gps_track_for_source(cfg.get("source", "fit"))
    probe = subprocess.run(
        [
            "ffprobe", "-v", "error", "-select_streams", "v:0",
            "-show_entries", "frame=best_effort_timestamp_time",
            "-of", "csv=p=0", str(ROOT / "Video" / "GX020079.mp4"),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    pts = [
        float(line.strip().rstrip(","))
        for line in probe.stdout.splitlines()
        if line.strip()
    ]

    result = {
        "preview_runtime_canvas": [960, 540],
        "export_runtime_canvas": [3840, 2160],
        "configured_zoom": int(cfg.get("zoom", 16)),
        "map_style": cfg.get("map_style", "light_all"),
        "layout": {
            "x_percent": cfg["x"], "y_percent": cfg["y"],
            "width_percent": cfg["size"], "height_percent": cfg["size"],
        },
        "cache_audit": {
            "renderer_key_before": ["gps_track identity", "configured zoom", "map style"],
            "renderer_key_after": ["gps_track identity", "effective zoom", "map style"],
            "grid_key": [
                "tile bounds", "zoom", "style", "draw_track",
                "track_color", "track_width",
            ],
            "preview_grid_can_be_reused_by_export": False,
            "cache_is_root_cause": False,
        },
        "frames": {},
    }

    for frame in FRAMES:
        target_dt = START_DT + timedelta(seconds=pts[frame])
        ts = _epoch(target_dt) - _epoch(gps_track[0][0])
        frame_result = {"pts": pts[frame], "map_ts": ts, "canvases": {}}
        normalized_routes = {}
        for canvas_w, canvas_h in CANVASES:
            widget = s(cfg["size"], canvas_w)
            plan = _map_render_plan(canvas_w, widget, int(cfg["zoom"]))
            old_renderer = MovingMapRenderer(
                gps_track, zoom=int(cfg["zoom"]), style=cfg["map_style"],
                marker_radius=int(cfg.get("marker_size", 7)),
                track_width=int(cfg.get("track_width", 3)),
            )
            new_renderer = MovingMapRenderer(
                gps_track, zoom=plan["effective_zoom"], style=cfg["map_style"],
                marker_radius=max(1, int(round(
                    float(cfg.get("marker_size", 7)) * (2 ** plan["zoom_offset"])
                ))),
                track_width=max(1, int(round(
                    int(cfg.get("track_width", 3)) * (2 ** plan["zoom_offset"])
                ))),
            )
            before = _geometry(old_renderer, ts, widget)
            after = _geometry(new_renderer, ts, plan["working_size"])
            normalized_routes[str(canvas_w)] = _route_normalized(new_renderer, after)
            map_img = new_renderer.render(
                ts, plan["working_size"], plan["working_size"],
                download_missing=False,
            )
            if map_img.size != (widget, widget):
                map_img = map_img.resize((widget, widget), Image.Resampling.LANCZOS)
            map_img.save(out_dir / f"frame_{frame}_{canvas_w}x{canvas_h}_map.png")
            frame_result["canvases"][str(canvas_w)] = {
                "canvas": [canvas_w, canvas_h],
                "layout_xy_px": [s(cfg["x"], canvas_w), s(cfg["y"], canvas_h)],
                "widget": [widget, widget],
                "scale_factor_vs_preview": canvas_w / 960.0,
                "before": {"zoom": int(cfg["zoom"]), **before},
                "after": {"render_plan": plan, **after},
            }

        ref_route = normalized_routes["960"]
        route_comparison = {}
        for width in (1920, 3840):
            candidate = normalized_routes[str(width)]
            max_delta = max(
                max(abs(a[0] - b[0]), abs(a[1] - b[1]))
                for a, b in zip(ref_route, candidate)
            )
            route_comparison[str(width)] = {
                "max_normalized_coordinate_delta": max_delta,
                "match_within_one_preview_pixel": max_delta <= (1 / 173) + 1e-12,
            }
        frame_result["route_comparison"] = route_comparison
        result["frames"][str(frame)] = frame_result

    output = out_dir / "map_parity_runtime.json"
    output.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
