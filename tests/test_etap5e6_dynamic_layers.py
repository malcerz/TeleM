"""ETAP 5E.6: dynamic average/label cache parity."""

from datetime import datetime, timedelta

import numpy as np

from src.indicators.chart import set_dynamic_layer_cache_enabled
from src.indicators.chart_builder import ChartHistory
from src.indicators.dispatcher import render_value_indicator


BASE = datetime(2026, 1, 1)


def _cfg(show_average):
    return {
        "enabled": True, "form": "chart", "x": 50.0, "y": 50.0,
        "size": 30.0, "font_size": 1.8, "min_val": 0.0, "max_val": 140.0,
        "chart_color": "#FFAA11", "fill_color": "#335577", "fill_alpha": 100,
        "show_grid": True, "show_average": show_average, "label_count": 3,
    }


def _render(key, history, target, enabled):
    cfg = _cfg(show_average=key == "fit_heart_rate_text")
    layout = {"global": {"text_outline": 3}, "indicators": {key: cfg}}
    set_dynamic_layer_cache_enabled(enabled)
    try:
        return render_value_indicator(
            640, 360, layout, "", key, 70.0,
            "BPM" if "heart" in key else "rpm", "HR" if "heart" in key else "Cad",
            cfg_override=cfg, formatted_val="70", history_data=history,
            current_position=0.5, target_dt=target,
        )[0]
    finally:
        set_dynamic_layer_cache_enabled(True)


def test_dynamic_average_and_label_layers_are_pixel_exact():
    values = [10.0, 0.0, None, 80.0, 40.0, 100.0]
    timestamps = [BASE + timedelta(seconds=value) for value in (0, 1, 2, 3, 10, 11)]
    history = ChartHistory(values, timestamps, chart_start_dt=BASE, chart_end_dt=timestamps[-1])
    for key in ("fit_cadence_text", "fit_heart_rate_text"):
        for seconds in (0.0, 0.8, 2.0, 3.1, 5.0, 10.5, 11.0):
            target = BASE + timedelta(seconds=seconds)
            reference = _render(key, history, target, False)
            cached = _render(key, history, target, True)
            delta = np.abs(np.asarray(reference, dtype=np.int16) - np.asarray(cached, dtype=np.int16))
            assert int(delta.max()) == 0, (key, seconds)
            assert int(np.any(delta != 0, axis=2).sum()) == 0, (key, seconds)
