"""Fixed-timeline progressive-reveal chart microbenchmark."""

from __future__ import annotations

import json
import statistics
import sys
import time
from bisect import bisect_right
from datetime import timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scratch.validate_etap5b6_direct import FPS, N, W, H, setup
from src.ffmpeg.worker_cache import WORKER_CACHE
from src.indicators.chart import set_dynamic_layer_cache_enabled
from src.indicators.dispatcher import render_value_indicator


def _summary(values):
    ordered = sorted(values)
    return {
        "avg_ms": statistics.fmean(values),
        "median_ms": statistics.median(values),
        "p95_ms": ordered[int((len(ordered) - 1) * 0.95)],
    }


def main() -> None:
    layout, _regions, _anchor, *_ = setup()
    histories = WORKER_CACHE["_precomputed_chart_data"]
    result = {}
    set_dynamic_layer_cache_enabled(True)
    for key in ("fit_cadence_text", "fit_heart_rate_text"):
        cfg = layout["indicators"][key]
        history = histories[key]
        samples = []
        for repeat in range(2000):
            frame = (repeat * (N - 1)) // 1999
            target = history.chart_start_dt + timedelta(seconds=frame / FPS)
            visible = bisect_right(history.timestamps, target) - 1
            value = history[visible] if visible >= 0 else None
            started = time.perf_counter()
            render_value_indicator(
                W, H, layout, "", key, value,
                "rpm" if key == "fit_cadence_text" else "BPM",
                cfg.get("label", key), cfg_override=cfg,
                formatted_val=f"{value:.0f}" if value is not None else "--",
                history_data=history, current_position=frame / (N - 1),
                target_dt=target,
            )
            samples.append((time.perf_counter() - started) * 1000.0)
        result[key] = _summary(samples)
    path = ROOT / "scratch" / "chart_fixed_timeline_benchmark.json"
    path.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()

