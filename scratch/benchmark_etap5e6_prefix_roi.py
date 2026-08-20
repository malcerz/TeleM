"""ETAP 5E.6: exact masked-paste prefix ROI microbenchmark."""

from __future__ import annotations

import json
import statistics
import sys
import time
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import src.indicators.chart as chart_module
from scratch.validate_etap5b6_direct import FPS, H, N, W, setup
from src.ffmpeg.worker_cache import WORKER_CACHE
from src.indicators.chart import set_dynamic_layer_cache_enabled
from src.indicators.dispatcher import render_value_indicator


def summary(values):
    ordered = sorted(values)
    return {
        "avg_ms": statistics.fmean(values),
        "median_ms": statistics.median(values),
        "p95_ms": ordered[int((len(ordered) - 1) * 0.95)],
    }


def main():
    layout, _regions, _anchor, *_ = setup()
    history = WORKER_CACHE["_precomputed_chart_data"]["fit_heart_rate_text"]
    cfg = layout["indicators"]["fit_heart_rate_text"]
    captured = []
    original = chart_module.get_history_chart_prefix_background

    def capture(*args, **kwargs):
        result = original(*args, **kwargs)
        captured.append(result[0].copy())
        return result

    chart_module.get_history_chart_prefix_background = capture
    try:
        for i in range(96):
            frame = i * (N - 1) // 95
            target = history.chart_start_dt + (history.chart_end_dt - history.chart_start_dt) * frame / (N - 1)
            visible = min(len(history) - 1, int(frame / (N - 1) * (len(history) - 1)))
            render_value_indicator(
                W, H, layout, "", "fit_heart_rate_text", history[visible], "BPM",
                cfg.get("label", "HR"), cfg_override=cfg,
                formatted_val=f"{history[visible]:.0f}", history_data=history,
                current_position=frame / (N - 1), target_dt=target,
            )
    finally:
        chart_module.get_history_chart_prefix_background = original

    bbox = captured[0].getchannel("A").getbbox()
    old_times, roi_times = [], []
    parity = []
    for i in range(2000):
        source = captured[i % len(captured)]
        base = Image.new("RGBA", (source.width + 8, source.height + 20), (0, 0, 0, 0))
        old = base.copy()
        started = time.perf_counter()
        old.paste((0, 0, 0, 0), (4, 10, 4 + source.width, 10 + source.height))
        old.paste(source, (4, 10), source)
        old_times.append((time.perf_counter() - started) * 1000.0)
        candidate = base.copy()
        started = time.perf_counter()
        x0, y0, x1, y1 = bbox
        candidate.paste((0, 0, 0, 0), (4 + x0, 10 + y0, 4 + x1, 10 + y1))
        cropped = source.crop(bbox)
        candidate.paste(cropped, (4 + x0, 10 + y0), cropped)
        roi_times.append((time.perf_counter() - started) * 1000.0)
        delta = np.abs(np.asarray(old, dtype=np.int16) - np.asarray(candidate, dtype=np.int16))
        parity.append((int(delta.max()), int(np.any(delta != 0, axis=2).sum())))
    result = {
        "source_size": list(captured[0].size),
        "cached_bbox": list(bbox),
        "full_area": captured[0].width * captured[0].height,
        "roi_area": (bbox[2] - bbox[0]) * (bbox[3] - bbox[1]),
        "before_full_clear_and_masked_paste": summary(old_times),
        "after_roi_clear_crop_and_masked_paste": summary(roi_times),
        "parity": {"max_diff": max(x[0] for x in parity), "different_pixels": max(x[1] for x in parity)},
    }
    destination = ROOT / "scratch" / "etap5e6_prefix_roi_benchmark.json"
    destination.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
