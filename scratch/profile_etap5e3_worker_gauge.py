"""ETAP 5E.3 worker-like compose profile, including the unchanged gauge."""

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

from scratch.validate_etap5b6_direct import FPS, H, N, W, setup
from src.ffmpeg.worker_cache import WORKER_CACHE
from src.indicators.compositor import compose_overlay
from src.indicators.profiling import get_overlay_profiler


def percentile(values, fraction):
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int((len(ordered) - 1) * fraction))]


def main():
    layout, _regions, _anchor, *_ = setup()
    cache = WORKER_CACHE["_telemetry_cache"]
    histories = WORKER_CACHE["_precomputed_chart_data"]
    profiler = get_overlay_profiler()
    if not profiler.enabled:
        raise RuntimeError("Set AMD_OVERLAY_PROFILE=1 before running this script")
    profiler._frames.clear()
    samples = []
    count = 300
    for repeat in range(count):
        index = (repeat * (N - 1)) // (count - 1)
        data = dict(cache.lookup(index))
        target = histories["fit_heart_rate_text"].chart_start_dt + timedelta(
            seconds=index / FPS
        )
        data["target_dt"] = target
        data["current_position"] = index / (N - 1)
        extra = dict(data.get("extra_indicators") or {})
        for key in ("fit_cadence_text", "fit_heart_rate_text"):
            history = histories[key]
            visible = bisect_right(history.timestamps, target) - 1
            value = history[visible] if visible >= 0 else None
            if key in extra:
                _old, unit, label = extra[key]
                extra[key] = (value, unit, label)
        data["extra_indicators"] = extra
        profiler.start_frame(index, W, H)
        started = time.perf_counter()
        compose_overlay(
            W, H, layout, "", _bboxes={}, reuse_canvas=False, **data
        )
        samples.append((time.perf_counter() - started) * 1000.0)
        profiler.finish_frame()
    summary = profiler.summary()
    metrics = summary["metrics"]
    names = [
        "indicator.fit_cadence_text.total",
        "indicator.fit_heart_rate_text.total",
        "indicator.fit_enhanced_speed_text.total",
        "indicator.fit_cadence_text.render",
        "indicator.fit_heart_rate_text.render",
        "indicator.fit_enhanced_speed_text.render",
        "indicator.fit_cadence_text.graph.background_and_chart_composite",
        "indicator.fit_heart_rate_text.graph.background_and_chart_composite",
        "indicator.fit_cadence_text.graph.prefix_static_build",
        "indicator.fit_heart_rate_text.graph.prefix_static_build",
    ]
    output = {
        "frames": count,
        "external_compose_ms": {
            "avg": statistics.fmean(samples),
            "median": statistics.median(samples),
            "p95": percentile(samples, 0.95),
        },
        "metrics": {name: metrics.get(name) for name in names},
        "all_metric_names": sorted(metrics),
    }
    destination = ROOT / "scratch" / "etap5e3_worker_gauge_profile.json"
    destination.write_text(json.dumps(output, indent=2), encoding="utf-8")
    print(json.dumps(output, indent=2))


if __name__ == "__main__":
    main()
