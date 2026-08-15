"""ETAP 5F — isolated causal cost of the 692→691 LANCZOS map resize.

Measures:
  1) the true single-call cost of Image.resize((691,691), LANCZOS) on a real
     692x692 map crop (profiler OFF, no nested double-counting),
  2) the full track_map indicator path for reference,
  3) a synthetic opaque 692x692 resize to separate Pillow's cost from tiles.
"""
from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
import time
from datetime import timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PIL import Image

from src.moving_map import MovingMapRenderer
from src.indicators.moving_map import _map_render_plan

sys.path.insert(0, str(ROOT / "scratch"))
from validate_compositing_etap5e import load_environment  # noqa: E402


def _percentile(values, p):
    ordered = sorted(values)
    pos = (len(ordered) - 1) * p
    lo, hi = int(math.floor(pos)), int(math.ceil(pos))
    if lo == hi:
        return ordered[lo]
    return ordered[lo] + (ordered[hi] - ordered[lo]) * (pos - lo)


def stats(vals):
    return {
        "avg": statistics.fmean(vals), "median": statistics.median(vals),
        "p95": _percentile(vals, 0.95), "p99": _percentile(vals, 0.99),
        "frames": len(vals),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--frames", type=int, default=120)
    args = parser.parse_args()

    telemetry, start, layout, speed, altitude, track, plan, pts = load_environment()
    gps_track = telemetry.fit_gps_track

    canvas_w, canvas_h = 3840, 2160
    zoom = int(layout["indicators"]["track_map"].get("zoom", 16))
    map_w = max(1, int(round((18.0 / 100.0) * canvas_w)))  # size_px for 4K
    map_h = map_w
    render_plan = _map_render_plan(canvas_w, map_w, zoom)
    effective_zoom = render_plan["effective_zoom"]
    working_size = render_plan["working_size"]
    print("audit:", json_dumps(render_plan))

    # Build the renderer exactly like _render_moving_map_indicator
    renderer = MovingMapRenderer(
        gps_track, zoom=effective_zoom, style=layout["indicators"]["track_map"].get("map_style", "light_all"),
        marker_color=(255, 255, 255, 255),
        marker_radius=max(1, int(round(7 * (2.0 ** render_plan["zoom_offset"])))),
        track_color=(255, 60, 30, 220),
        track_width=max(1, int(round(3 * (2.0 ** render_plan["zoom_offset"])))),
    )

    resize_times = []
    render_times = []
    full_times = []
    n = min(args.frames, len(pts))
    samples = []
    for i in range(n):
        target = start + timedelta(seconds=pts[i])
        gps0 = gps_track[0][0]
        target_epoch = (target.timestamp() if target.tzinfo is not None
                        else target.replace(tzinfo=timezone.utc).timestamp())
        gps0_ts = (gps0.timestamp() if gps0.tzinfo is not None
                   else gps0.replace(tzinfo=timezone.utc).timestamp())
        ts = target_epoch - gps0_ts

        t0 = time.perf_counter()
        map_img = renderer.render(ts, working_size, working_size, download_missing=False)
        t1 = time.perf_counter()
        # isolated resize: fresh copy per iteration (production creates new each frame)
        if map_img.size != (map_w, map_h):
            out = map_img.resize((map_w, map_h), Image.Resampling.LANCZOS)
        else:
            out = map_img
        t2 = time.perf_counter()
        resize_times.append((t2 - t1) * 1000.0)
        render_times.append((t1 - t0) * 1000.0)
        full_times.append((t2 - t0) * 1000.0)
        samples.append((map_img, out))

    print("=== REAL 692x692 map crop -> 691 LANCZOS ===")
    print("resize-only  :", json_dumps(stats(resize_times)))
    print("render(crop) :", json_dumps(stats(render_times)))
    print("render+resize:", json_dumps(stats(full_times)))
    print("working_size:", working_size, "map_w:", map_w, "map_img.size:", samples[0][0].size,
          "out.size:", samples[0][1].size)

    # synthetic opaque 692x692 -> 691 LANCZOS (Pillow cost only, no tiles/marker)
    syn = Image.new("RGBA", (692, 692), (120, 90, 60, 255))
    syn_times = []
    for _ in range(n):
        t0 = time.perf_counter()
        syn.resize((691, 691), Image.Resampling.LANCZOS)
        syn_times.append((time.perf_counter() - t0) * 1000.0)
    print("\n=== synthetic 692x692 opaque -> 691 LANCZOS ===")
    print("resize-only  :", json_dumps(stats(syn_times)))
    return 0


def json_dumps(d):
    return json.dumps(d)


if __name__ == "__main__":
    main()
