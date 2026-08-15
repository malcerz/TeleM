"""ETAP 5F — candidate comparison for the 692→691 map resize (pixel-exact gate).

Candidates:
  A. REFERENCE      : render 692 -> Image.resize((691,691), LANCZOS)
  B. DIRECT 691     : render directly at 691 (no resize)
  C. TRANSFORM      : N/A - Pillow Image.transform (AFFINE) does NOT support
                      LANCZOS resample (only NEAREST/BILINEAR/BICUBIC).
  D. CROP-CENTER 691: render 692 -> crop center 691 (no resample)

For every frame the pixel output of each candidate is compared against A.
Any mismatch => REJECT (even if faster).  Times are single-call wall clocks.
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

import numpy as np
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
    if not vals:
        return {}
    return {
        "avg": statistics.fmean(vals), "median": statistics.median(vals),
        "p95": _percentile(vals, 0.95), "p99": _percentile(vals, 0.99),
        "frames": len(vals),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--frames", type=int, default=1131)
    args = parser.parse_args()

    telemetry, start, layout, speed, altitude, track, plan, pts = load_environment()
    gps_track = telemetry.fit_gps_track
    canvas_w, canvas_h = 3840, 2160
    zoom = int(layout["indicators"]["track_map"].get("zoom", 16))
    map_w = max(1, int(round((18.0 / 100.0) * canvas_w)))
    rp = _map_render_plan(canvas_w, map_w, zoom)
    eff_zoom = rp["effective_zoom"]
    working = rp["working_size"]

    renderer = MovingMapRenderer(
        gps_track, zoom=eff_zoom, style=layout["indicators"]["track_map"].get("map_style", "light_all"),
        marker_color=(255, 255, 255, 255),
        marker_radius=max(1, int(round(7 * (2.0 ** rp["zoom_offset"])))),
        track_color=(255, 60, 30, 220),
        track_width=max(1, int(round(3 * (2.0 ** rp["zoom_offset"])))),
    )

    n = min(args.frames, len(pts))
    cmp = {"B": [], "D": []}
    time_A, time_B, time_D = [], [], []

    for i in range(n):
        target = start + timedelta(seconds=pts[i])
        gps0 = gps_track[0][0]
        target_epoch = (target.timestamp() if target.tzinfo is not None
                        else target.replace(tzinfo=timezone.utc).timestamp())
        gps0_ts = (gps0.timestamp() if gps0.tzinfo is not None
                   else gps0.replace(tzinfo=timezone.utc).timestamp())
        ts = target_epoch - gps0_ts

        # A: reference 692 -> LANCZOS 691
        t0 = time.perf_counter()
        m692 = renderer.render(ts, working, working, download_missing=False)
        ref = m692.resize((map_w, map_w), Image.Resampling.LANCZOS)
        time_A.append((time.perf_counter() - t0) * 1000.0)
        ref_np = np.asarray(ref, dtype=np.uint8)

        # B: direct 691 render
        t0 = time.perf_counter()
        m691 = renderer.render(ts, map_w, map_w, download_missing=False)
        time_B.append((time.perf_counter() - t0) * 1000.0)
        b_np = np.asarray(m691, dtype=np.uint8)
        d = np.abs(ref_np.astype(np.int16) - b_np.astype(np.int16))
        cmp["B"].append((int(d.max()), float(d.mean())))

        # D: 692 -> center crop 691 (no resample)
        t0 = time.perf_counter()
        off = (working - map_w) // 2
        d_img = m692.crop((off, off, off + map_w, off + map_w))
        time_D.append((time.perf_counter() - t0) * 1000.0)
        d_np = np.asarray(d_img, dtype=np.uint8)
        d = np.abs(ref_np.astype(np.int16) - d_np.astype(np.int16))
        cmp["D"].append((int(d.max()), float(d.mean())))

    print("=== candidate times (ms) ===")
    for k, t in (("A REF LANCZOS", time_A), ("B direct 691", time_B), ("D crop691", time_D)):
        print(f"{k:14s}", json.dumps(stats(t)))
    print("\n=== pixel vs REFERENCE A ===")
    for k in ("B", "D"):
        mxs = [x[0] for x in cmp[k]]
        meas = [x[1] for x in cmp[k]]
        mism = sum(1 for x in mxs if x > 0)
        print(f"{k}: frames={len(mxs)} mismatching={mism} MAX={max(mxs)} MAE={statistics.fmean(meas):.6f} "
              f"P95_MAX={_percentile(mxs,0.95)} P99_MAX={_percentile(mxs,0.99)}")
    return 0


if __name__ == "__main__":
    main()
