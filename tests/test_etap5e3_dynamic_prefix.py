"""Fixed-timeline progressive-reveal chart regression coverage."""

from datetime import datetime, timedelta

import numpy as np

from src.indicators.chart_builder import ChartHistory
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
    timestamps = [BASE + timedelta(seconds=value) for value in seconds]
    return ChartHistory(
        list(values), timestamps,
        chart_start_dt=BASE,
        chart_end_dt=timestamps[-1],
    )


def _render(key, history, target, value):
    cfg = _cfg(show_average=key == "fit_heart_rate_text")
    layout = {"global": {"text_outline": 3}, "indicators": {key: cfg}}
    return render_value_indicator(
        640, 360, layout, "", key, value, "BPM" if "heart" in key else "rpm",
        "Heart Rate" if "heart" in key else "Cadence",
        cfg_override=cfg, formatted_val=str(int(value)) if value is not None else "—",
        history_data=history, current_position=0.5, target_dt=target,
    )[0]


def test_repeated_visible_index_keeps_exact_current_time_semantics():
    history = _history([0.0, 80.0, 0.0, 100.0], [0.0, 1.0, 2.0, 10.0])
    first = _render("fit_heart_rate_text", history, BASE + timedelta(seconds=1.1), 80.0)
    second = _render("fit_heart_rate_text", history, BASE + timedelta(seconds=1.8), 80.0)
    # Both frames expose the same samples, but the marker must still move on
    # the fixed activity timeline. A cache keyed only by visible index may not
    # freeze the full dynamic chart image.
    assert not np.array_equal(np.asarray(first), np.asarray(second))


def test_repeated_state_matches_naive_correct_prefix_and_preserves_zero_gap():
    history = _history([10.0, 0.0, None, 30.0, 40.0], [0.0, 1.0, 2.0, 10.0, 11.0])
    cfg = _cfg(show_average=False)
    key = "fit_heart_rate_text"
    layout = {"global": {"text_outline": 3}, "indicators": {key: cfg, "fit_power_text": dict(cfg)}}
    for seconds, count in ((1.1, 2), (5.0, 3), (10.1, 4), (10.8, 4), (11.0, 5)):
        target = BASE + timedelta(seconds=seconds)
        optimized = render_value_indicator(
            640, 360, layout, "", key, 40.0, "BPM", "Heart Rate",
            cfg_override=cfg, formatted_val="40", history_data=history,
            current_position=0.5, target_dt=target,
        )[0]
        prefix = ChartHistory(
            list(history[:count]), list(history.timestamps[:count]),
            chart_start_dt=history.chart_start_dt, chart_end_dt=history.chart_end_dt,
        )
        reference = render_value_indicator(
            640, 360, layout, "", "fit_power_text", 40.0, "BPM", "Heart Rate",
            cfg_override=cfg, formatted_val="40", history_data=prefix,
            current_position=1.0, target_dt=target,
        )[0]
        assert np.array_equal(np.asarray(optimized), np.asarray(reference)), seconds
    assert history[1] == 0.0
    assert history[2] is None
