"""ETAP 5E.1 chart renderer A/B benchmark."""

from __future__ import annotations

import json
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scratch.validate_etap5b6_direct import N, W, H, setup
from src.ffmpeg.worker_cache import WORKER_CACHE
from src.indicators.chart_builder import ChartHistory
from src.indicators.dispatcher import render_value_indicator


def percentile(values, fraction):
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int((len(ordered) - 1) * fraction))]


def measure(fn, count=1000):
    values = []
    for index in range(count):
        started = time.perf_counter()
        fn(index)
        values.append((time.perf_counter() - started) * 1000.0)
    return {
        "avg_ms": statistics.fmean(values),
        "median_ms": statistics.median(values),
        "p95_ms": percentile(values, 0.95),
    }


def main():
    layout, _regions, _anchor, _speed, _track, _alt = setup()
    chart_data = WORKER_CACHE["_precomputed_chart_data"]
    result = {}
    for key in ("fit_cadence_text", "fit_heart_rate_text"):
        history = chart_data[key]
        cfg = layout["indicators"][key]
        legacy_cfg = dict(cfg)
        legacy_key = "fit_power_text"
        legacy_layout = {"global": layout.get("global", {}), "indicators": {legacy_key: legacy_cfg}}
        targets = [
            history.chart_start_dt + (history.chart_end_dt - history.chart_start_dt) * index / 999
            for index in range(1000)
        ]
        values = []
        for index in range(1000):
            sample_index = min(len(history) - 1, int(index / 999 * (len(history) - 1)))
            values.append(history[sample_index] if history[sample_index] is not None else 0.0)

        def render_old(index):
            # The ETAP 5E baseline: static full-history chart, no target time,
            # with only the marker position changing.
            render_value_indicator(
                W, H, layout, "", key, values[index], "rpm" if "cadence" in key else "BPM",
                cfg.get("label", key), cfg_override=cfg, formatted_val="42",
                history_data=history, current_position=index / 999,
            )

        def render_naive(index):
            target = targets[index]
            count = sum(ts <= target for ts in history.timestamps)
            prefix = ChartHistory(
                list(history[:count]), list(history.timestamps[:count]),
                chart_start_dt=history.chart_start_dt, chart_end_dt=target,
            )
            render_value_indicator(
                W, H, legacy_layout, "", legacy_key, values[index],
                "rpm" if "cadence" in key else "BPM", cfg.get("label", key),
                cfg_override=legacy_cfg, formatted_val="42", history_data=prefix,
                current_position=1.0, target_dt=target,
            )

        def render_optimized(index):
            target = targets[index]
            render_value_indicator(
                W, H, layout, "", key, values[index], "rpm" if "cadence" in key else "BPM",
                cfg.get("label", key), cfg_override=cfg, formatted_val="42",
                history_data=history, current_position=index / 999, target_dt=target,
            )

        # Warm the immutable caches before collecting samples.
        render_old(500); render_naive(500); render_optimized(500)
        result[key] = {
            "current_cached_full_history": measure(render_old),
            "naive_correct_prefix": measure(render_naive),
            "optimized_correct_prefix": measure(render_optimized),
        }
    destination = ROOT / "scratch" / "etap5e1_prefix_benchmark.json"
    destination.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
