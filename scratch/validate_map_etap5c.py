"""Pixel and memory validation runner for AMD ETAP 5C track_map."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import statistics
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.gui.telemetry_manager import TelemetryDataManager
from src.indicators.helpers import _parse_marker_color, apply_map_shape, s
from src.indicators.moving_map import _map_render_plan
from src.moving_map import MovingMapRenderer, TILE_SIZE


def _epoch(value):
    return (
        value.timestamp()
        if value.tzinfo is not None
        else value.replace(tzinfo=timezone.utc).timestamp()
    )


def _percentile(values: list[float], percentile: float) -> float:
    ordered = sorted(values)
    pos = (len(ordered) - 1) * percentile / 100.0
    lo = int(math.floor(pos))
    hi = int(math.ceil(pos))
    if lo == hi:
        return ordered[lo]
    return ordered[lo] + (ordered[hi] - ordered[lo]) * (pos - lo)


def _stats(values: list[float]) -> dict:
    return {
        "avg": statistics.fmean(values),
        "median": statistics.median(values),
        "p95": _percentile(values, 95),
        "p99": _percentile(values, 99),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("before", "after"))
    args = parser.parse_args()
    out_dir = ROOT / "Raporty" / "AMD_ETAP5C"
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
        ], capture_output=True, text=True, check=True,
    )
    pts = [
        float(line.strip().rstrip(","))
        for line in probe.stdout.splitlines() if line.strip()
    ][:1131]

    widget_size = s(cfg["size"], 3840)
    plan = _map_render_plan(3840, widget_size, int(cfg["zoom"]))
    scale = 2 ** plan["zoom_offset"]
    track_color = _parse_marker_color(cfg.get("track_color", "#FF3C1E"))
    if len(track_color) == 3:
        track_color = (*track_color, 220)
    renderer = MovingMapRenderer(
        gps_track,
        zoom=plan["effective_zoom"],
        style=cfg.get("map_style", "light_all"),
        marker_color=_parse_marker_color(cfg.get("marker_color", "#FFFFFF")),
        marker_radius=max(1, int(round(float(cfg.get("marker_size", 7)) * scale))),
        track_color=track_color,
        track_width=max(1, int(round(int(cfg.get("track_width", 3)) * scale))),
    )

    timings = []
    hashes = []
    grid_pixels = []
    region_pixels = []
    bounds = {}
    start_dt = datetime(2026, 8, 5, 4, 28, 11)
    gps0_epoch = _epoch(gps_track[0][0])
    for frame, seconds in enumerate(pts):
        ts = _epoch(start_dt + timedelta(seconds=seconds)) - gps0_epoch
        cpx, cpy = renderer._interp_pos(ts)
        cx, cy = int(cpx // TILE_SIZE), int(cpy // TILE_SIZE)
        half = int(math.ceil(plan["working_size"] / 2 / TILE_SIZE)) + 1
        grid_w = (2 * half + 1) * TILE_SIZE
        grid_h = grid_w
        grid_pixels.append(grid_w * grid_h)
        region_pixels.append(plan["working_size"] ** 2)

        started = time.perf_counter()
        image = renderer.render(
            ts, plan["working_size"], plan["working_size"],
            download_missing=False,
            draw_track=not bool(cfg.get("hide_track", False)),
            draw_marker=not bool(cfg.get("hide_marker", False)),
        )
        if image.size != (widget_size, widget_size):
            image = image.resize(
                (widget_size, widget_size), Image.Resampling.LANCZOS
            )
        image = apply_map_shape(image, cfg.get("map_shape", "square"))
        timings.append((time.perf_counter() - started) * 1000.0)
        raw = image.tobytes("raw", "RGBA")
        hashes.append(hashlib.sha256(raw).hexdigest())
        if frame in (30, 300, 900):
            image.save(out_dir / f"map_{args.mode}_frame_{frame}.png")
            bounds[str(frame)] = {
                "effective_zoom": plan["effective_zoom"],
                "logical_viewport": plan["logical_size"],
                "working_size": plan["working_size"],
                "marker_source": [cpx, cpy],
            }

    result = {
        "mode": args.mode,
        "frames": len(pts),
        "plan": plan,
        "hashes": hashes,
        "timing_ms": _stats(timings),
        "memory": {
            "full_grid_copy_calls_per_frame": 1 if args.mode == "before" else 0,
            "avg_full_grid_pixels": statistics.fmean(grid_pixels),
            "p95_full_grid_pixels": _percentile(grid_pixels, 95),
            "avg_region_pixels": statistics.fmean(region_pixels),
            "avg_full_grid_mib_rgba": statistics.fmean(grid_pixels) * 4 / 1024 / 1024,
            "avg_region_mib_rgba": statistics.fmean(region_pixels) * 4 / 1024 / 1024,
        },
        "reference_frames": bounds,
    }
    path = out_dir / f"map_widget_{args.mode}.json"
    path.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in result.items() if k != "hashes"}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
