"""ETAP 5E.6: full worker-like indicator ranking after cache deployment."""

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


def pct(values, fraction):
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int((len(ordered) - 1) * fraction))]


def main():
    layout, _regions, _anchor, *_ = setup()
    profiler = get_overlay_profiler()
    if not profiler.enabled:
        raise RuntimeError("Set AMD_OVERLAY_PROFILE=1")
    cache = WORKER_CACHE["_telemetry_cache"]
    histories = WORKER_CACHE["_precomputed_chart_data"]
    profiler._frames.clear()
    external = []
    for repeat in range(300):
        index = repeat * (N - 1) // 299
        data = dict(cache.lookup(index))
        target = histories["fit_heart_rate_text"].chart_start_dt + timedelta(seconds=index / FPS)
        data["target_dt"] = target
        data["current_position"] = index / (N - 1)
        extra = dict(data.get("extra_indicators") or {})
        for key in ("fit_cadence_text", "fit_heart_rate_text"):
            history = histories[key]
            visible = bisect_right(history.timestamps, target) - 1
            if key in extra:
                _old, unit, label = extra[key]
                extra[key] = (history[visible] if visible >= 0 else None, unit, label)
        data["extra_indicators"] = extra
        profiler.start_frame(index, W, H)
        started = time.perf_counter()
        compose_overlay(W, H, layout, "", _bboxes={}, reuse_canvas=False, **data)
        external.append((time.perf_counter() - started) * 1000.0)
        profiler.finish_frame()
    metrics = profiler.summary()["metrics"]
    ranking = {}
    for name, value in metrics.items():
        if name.startswith("indicator.") and name.endswith(".total"):
            ranking[name] = value
    result = {
        "external_compose_ms": {"avg": statistics.fmean(external), "median": statistics.median(external), "p95": pct(external, .95)},
        "indicator_total_ranking": dict(sorted(ranking.items(), key=lambda item: item[1]["avg_ms"], reverse=True)),
        "selected_metrics": {name: value for name, value in metrics.items() if any(token in name for token in ("graph.background_and_chart_composite", "graph.dynamic_labels", "graph.prefix.average", "paste_composite"))},
    }
    destination = ROOT / "scratch" / "etap5e6_worker_full_profile.json"
    destination.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
