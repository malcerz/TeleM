"""ETAP 5E.6: 1000-frame post-change internal chart profiler."""

from __future__ import annotations

import json
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scratch.profile_etap5e_charts import _pct
from scratch.validate_etap5b6_direct import FPS, N, W, H, setup
from src.ffmpeg.worker_cache import WORKER_CACHE
from src.indicators.chart import (
    get_dynamic_layer_cache_stats,
    reset_dynamic_layer_cache_stats,
    set_dynamic_layer_cache_enabled,
)
from src.indicators.dispatcher import render_value_indicator
from src.indicators.profiling import get_overlay_profiler, indicator_scope


def main():
    layout, _regions, _anchor, *_ = setup()
    profiler = get_overlay_profiler()
    if not profiler.enabled:
        raise RuntimeError("Set AMD_OVERLAY_PROFILE=1 before running this script")
    histories = WORKER_CACHE["_precomputed_chart_data"]
    results = {}
    for key in ("fit_cadence_text", "fit_heart_rate_text"):
        history = histories[key]
        cfg = layout["indicators"][key]
        reset_dynamic_layer_cache_stats()
        set_dynamic_layer_cache_enabled(True)
        profiler._frames.clear()
        samples = []
        for repeat in range(1000):
            index = (repeat * (N - 1)) // 999
            target_dt = history.chart_start_dt + ((history.chart_end_dt - history.chart_start_dt) * index / (N - 1))
            value = history[min(len(history) - 1, int((index / (N - 1)) * (len(history) - 1)))]
            profiler.start_frame(index, W, H)
            started = time.perf_counter()
            with indicator_scope(key):
                render_value_indicator(
                    W, H, layout, "", key, value,
                    "rpm" if key == "fit_cadence_text" else "BPM",
                    cfg.get("label", key), cfg_override=cfg,
                    formatted_val=f"{value:.0f}" if value is not None else "--",
                    history_data=history, current_position=index / (N - 1),
                    target_dt=target_dt,
                )
            samples.append((time.perf_counter() - started) * 1000.0)
            profiler.finish_frame()
        summary = profiler.summary()
        results[key] = {
            "render_ms": {
                "avg": statistics.fmean(samples),
                "median": statistics.median(samples),
                "p95": _pct(samples, .95),
            },
            "metrics": {
                name: data for name, data in summary["metrics"].items()
                if f"indicator.{key}." in name
            },
            "cache": get_dynamic_layer_cache_stats(),
        }
    set_dynamic_layer_cache_enabled(True)
    destination = ROOT / "scratch" / "etap5e6_internal_after.json"
    destination.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
