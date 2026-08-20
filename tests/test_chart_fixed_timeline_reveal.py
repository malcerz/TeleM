"""Regression tests for the fixed activity timeline chart contract."""

from datetime import datetime, timedelta

import numpy as np
import pytest

from src.indicators import chart as chart_module
from src.indicators.chart_builder import ChartHistory
from src.indicators.chart_utils import get_history_chart_prefix_background
from src.indicators.dispatcher import render_value_indicator


BASE = datetime(2026, 1, 1)


def _cfg(show_average=False):
    return {
        "enabled": True,
        "form": "chart",
        "x": 50.0,
        "y": 50.0,
        "size": 30.0,
        "font_size": 1.8,
        "min_val": 0.0,
        "max_val": 120.0,
        "chart_color": "#FF0000",
        "fill_color": "#00FF00",
        "fill_alpha": 100,
        "show_grid": True,
        "show_average": show_average,
    }


def _history(values, seconds):
    timestamps = [BASE + timedelta(seconds=second) for second in seconds]
    return ChartHistory(
        values, timestamps,
        chart_start_dt=BASE,
        chart_end_dt=timestamps[-1],
    )


def _capture_marker(monkeypatch, key, history, target):
    captured = {}
    original = chart_module._draw_post_paste_cursor

    def capture(*args, **kwargs):
        captured["points"] = args[1]
        captured["current_index"] = args[2]
        return original(*args, **kwargs)

    monkeypatch.setattr(chart_module, "_draw_post_paste_cursor", capture)
    cfg = _cfg(show_average=key == "fit_heart_rate_text")
    layout = {"global": {"text_outline": 3}, "indicators": {key: cfg}}
    render_value_indicator(
        640, 360, layout, "", key, 50.0,
        "BPM" if key == "fit_heart_rate_text" else "rpm",
        "Heart Rate" if key == "fit_heart_rate_text" else "Cadence",
        cfg_override=cfg, formatted_val="50", history_data=history,
        current_position=0.0, target_dt=target,
    )
    return captured["points"], captured["current_index"]


@pytest.mark.parametrize("key", ["fit_cadence_text", "fit_heart_rate_text"])
def test_fixed_activity_timeline_marker_and_sample_x(monkeypatch, key):
    seconds = [0, 10, 25, 50, 75, 100]
    history = _history([0.0, 20.0, 40.0, 60.0, 80.0, 100.0], seconds)
    sample_x_at_25 = []

    for percent in (10, 25, 50, 75, 100):
        points, marker = _capture_marker(
            monkeypatch, key, history, BASE + timedelta(seconds=percent),
        )
        assert marker is not None
        marker_x, _ = marker
        expected_x = points[0][0] + (percent / 100.0) * (points[-1][0] - points[0][0])
        assert marker_x == pytest.approx(expected_x, abs=0.001)
        if percent >= 25:
            sample_x_at_25.append(points[2][0])

    assert sample_x_at_25 == [sample_x_at_25[0]] * len(sample_x_at_25)


def test_future_plot_area_stays_empty_and_fit_gap_keeps_its_width():
    history = _history([10.0, 20.0, 30.0, 40.0, 50.0], [0, 1, 2, 20, 21])
    kwargs = dict(
        line_color=(255, 0, 0), fill_color=(0, 255, 0), fill_alpha=100,
        line_thickness=2, show_axes=True, grid_color=(68, 68, 68, 255),
        custom_min_val=0.0, custom_max_val=60.0,
    )

    prefix, points, *_ = get_history_chart_prefix_background(
        history, BASE + timedelta(seconds=2), 200, 80, **kwargs,
    )
    pixels = np.asarray(prefix)
    after_current = pixels[:, int(points[2][0]) + 2:, :3]
    is_series = (
        ((after_current[:, :, 0] == 255) & (after_current[:, :, 1] == 0) & (after_current[:, :, 2] == 0))
        | ((after_current[:, :, 0] == 0) & (after_current[:, :, 1] == 255) & (after_current[:, :, 2] == 0))
    )
    assert not is_series.any()

    full, full_points, *_ = get_history_chart_prefix_background(
        history, BASE + timedelta(seconds=21), 200, 80, **kwargs,
    )
    full_pixels = np.asarray(full)
    gap = full_pixels[:, int(full_points[2][0]) + 2:int(full_points[3][0]) - 2, :3]
    is_line = (gap[:, :, 0] == 255) & (gap[:, :, 1] == 0) & (gap[:, :, 2] == 0)
    assert not is_line.any()

