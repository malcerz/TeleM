"""ETAP 5E reproducible chart-only profiler on the production layout."""

from __future__ import annotations

import json
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scratch.validate_etap5b6_direct import FPS, N, W, H, setup
from src.indicators.dispatcher import render_value_indicator
from src.indicators.profiling import get_overlay_profiler, indicator_scope
from src.ffmpeg.worker_cache import WORKER_CACHE


def _pct(values: list[float], fraction: float) -> float:
    values = sorted(values)
    return values[min(len(values) - 1, int((len(values) - 1) * fraction))]


def main() -> None:
    layout, _regions, anchor, speed, track, alt = setup()
    profiler = get_overlay_profiler()
    if not profiler.enabled:
        raise RuntimeError("Set AMD_OVERLAY_PROFILE=1 before running this script")
    cache = WORKER_CACHE["_telemetry_cache"]
    results = {}
    for key in ("fit_cadence_text", "fit_heart_rate_text"):
        cfg = layout["indicators"][key]
        history = WORKER_CACHE["_precomputed_chart_data"][key]
        samples = []
        profiler._frames.clear()
        for repeat in range(1000):
            index = (repeat * (N - 1)) // 999
            frame = cache.lookup(index)
            target_dt = history.chart_start_dt + (
                (history.chart_end_dt - history.chart_start_dt) * index / (N - 1)
            )
            current_position = index / (N - 1)
            value = history[min(len(history) - 1, int(current_position * (len(history) - 1)))]
            started = time.perf_counter()
            profiler.start_frame(index, W, H)
            with indicator_scope(key):
                render_value_indicator(
                    W, H, layout, "", key, value, "rpm" if key.endswith("cadence_text") else "BPM",
                    cfg.get("label", key), cfg_override=cfg,
                    formatted_val=f"{value:.0f}", history_data=history,
                    current_position=current_position, target_dt=target_dt,
                )
            profiler.finish_frame()
            samples.append((time.perf_counter() - started) * 1000.0)
        summary = profiler.summary()
        metrics = summary["metrics"]
        own = {
            name: data for name, data in metrics.items()
            if f"indicator.{key}." in name
        }
        results[key] = {
            "render_ms": {
                "avg": statistics.fmean(samples), "median": statistics.median(samples),
                "p95": _pct(samples, .95),
            },
            "metrics": own,
        }
    destination = ROOT / "scratch" / "etap5e_chart_profile_before.json"
    destination.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
