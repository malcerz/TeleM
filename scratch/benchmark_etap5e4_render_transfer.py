"""ETAP 5E.4: isolate local chart render from rotated_paste transfer."""

from __future__ import annotations

import json
import statistics
import sys
import time
from bisect import bisect_right
from datetime import timedelta
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scratch.validate_etap5b6_direct import FPS, H, N, W, setup
from src.ffmpeg.worker_cache import WORKER_CACHE
from src.indicators.dispatcher import render_value_indicator
from src.indicators.rotated_paste import rotated_paste


def percentile(values, fraction):
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int((len(ordered) - 1) * fraction))]


def summary(values):
    return {
        "avg_ms": statistics.fmean(values),
        "median_ms": statistics.median(values),
        "p95_ms": percentile(values, 0.95),
    }


def main():
    layout, regions, _anchor, *_ = setup()
    histories = WORKER_CACHE["_precomputed_chart_data"]
    region = regions[3]
    _dest_x, _dest_y, atlas_x, atlas_y, _rw, _rh = region
    result = {}
    for key in ("fit_cadence_text", "fit_heart_rate_text"):
        history = histories[key]
        cfg = layout["indicators"][key]
        unit = "rpm" if key == "fit_cadence_text" else "BPM"
        label = cfg.get("label", key)
        renders, transfers, combined = [], [], []
        for repeat in range(1000):
            frame = (repeat * (N - 1)) // 999
            target = history.chart_start_dt + timedelta(seconds=frame / FPS)
            visible = bisect_right(history.timestamps, target) - 1
            value = history[visible] if visible >= 0 else 0.0
            started = time.perf_counter()
            res, rx, ry, _extra = render_value_indicator(
                W, H, layout, "", key, value, unit, label,
                cfg_override=cfg, formatted_val=f"{value:.0f}",
                history_data=history, current_position=frame / (N - 1),
                target_dt=target,
            )
            render_done = time.perf_counter()
            atlas = Image.new("RGBA", (1900, 762), (0, 0, 0, 0))
            rotated_paste(
                atlas, res, rx - (region[0] - atlas_x), ry - (region[1] - atlas_y),
                0, prior_bboxes=[], cache_key=key,
            )
            finished = time.perf_counter()
            renders.append((render_done - started) * 1000.0)
            transfers.append((finished - render_done) * 1000.0)
            combined.append((finished - started) * 1000.0)
        result[key] = {
            "local_render": summary(renders),
            "rotated_paste_alpha_transfer": summary(transfers),
            "render_plus_transfer": summary(combined),
        }
    destination = ROOT / "scratch" / "etap5e4_render_transfer.json"
    destination.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
