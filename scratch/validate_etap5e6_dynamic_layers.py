"""ETAP 5E.6: local chart A/B parity and bounded-cache hit-rate audit."""

from __future__ import annotations

import json
import sys
from bisect import bisect_right
from datetime import timedelta
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scratch.validate_etap5b6_direct import FPS, H, N, W, setup
from src.ffmpeg.worker_cache import WORKER_CACHE
from src.indicators.chart import (
    get_dynamic_layer_cache_stats,
    reset_dynamic_layer_cache_stats,
    set_dynamic_layer_cache_enabled,
)
from src.indicators.dispatcher import render_value_indicator


def _render(layout, key, history, frame):
    cfg = layout["indicators"][key]
    target = history.chart_start_dt + timedelta(seconds=frame / FPS)
    visible = bisect_right(history.timestamps, target) - 1
    value = history[visible] if visible >= 0 else None
    return render_value_indicator(
        W, H, layout, "", key, value,
        "rpm" if key == "fit_cadence_text" else "BPM",
        cfg.get("label", key), cfg_override=cfg,
        formatted_val=f"{value:.0f}" if value is not None else "--",
        history_data=history, current_position=frame / (N - 1),
        target_dt=target,
    )[0]


def _diff(left, right):
    delta = np.abs(np.asarray(left, dtype=np.int16) - np.asarray(right, dtype=np.int16))
    return int(delta.max()), int(np.any(delta != 0, axis=2).sum())


def main():
    layout, _regions, _anchor, *_ = setup()
    histories = WORKER_CACHE["_precomputed_chart_data"]
    checkpoints = [0, 540, 1350, 2700, 4050, 4860, 5399]
    result = {"parity": {}, "cache_stats_5400": {}}

    for key in ("fit_cadence_text", "fit_heart_rate_text"):
        history = histories[key]
        result["parity"][key] = {}
        for frame in checkpoints:
            set_dynamic_layer_cache_enabled(False)
            reference = _render(layout, key, history, frame)
            set_dynamic_layer_cache_enabled(True)
            candidate = _render(layout, key, history, frame)
            result["parity"][key][str(frame)] = dict(zip(
                ("max_diff", "different_pixels"), _diff(reference, candidate)
            ))

        reset_dynamic_layer_cache_stats()
        set_dynamic_layer_cache_enabled(True)
        for frame in range(N):
            _render(layout, key, history, frame)
        result["cache_stats_5400"][key] = get_dynamic_layer_cache_stats()

    set_dynamic_layer_cache_enabled(True)
    destination = ROOT / "scratch" / "etap5e6_dynamic_layer_validation.json"
    destination.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
