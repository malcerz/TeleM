from bisect import bisect_right
from datetime import datetime, timedelta

import numpy as np

from src.indicators.chart_builder import ChartHistory
from src.indicators.chart_utils import _chart_segment_ranges, _split_chart_segments
from src.indicators.dispatcher import render_value_indicator


BASE = datetime(2026, 1, 1)


def _cfg():
    return {
        "enabled": True,
        "form": "chart",
        "x": 50.0,
        "y": 50.0,
        "size": 30.0,
        "font_size": 1.8,
        "min_val": 0.0,
        "max_val": 100.0,
        "chart_color": "#FF0000",
        "fill_color": "#00FF00",
        "fill_alpha": 100,
        "show_grid": True,
    }


def _history(seconds, values, end=None):
    timestamps = [BASE + timedelta(seconds=value) for value in seconds]
    return ChartHistory(
        list(values), timestamps,
        chart_start_dt=BASE,
        chart_end_dt=BASE + timedelta(seconds=end if end is not None else seconds[-1]),
    )


def _render_pair(history, current_seconds, key="fit_cadence_text"):
    target = BASE + timedelta(seconds=current_seconds)
    count = bisect_right(history.timestamps, target)
    prefix = ChartHistory(
        list(history[:count]), list(history.timestamps[:count]),
        chart_start_dt=BASE, chart_end_dt=target,
    )
    cfg = _cfg()
    legacy_key = "fit_power_text"
    layout = {"global": {"text_outline": 3}, "indicators": {
        key: cfg, legacy_key: dict(cfg),
    }}
    optimized = render_value_indicator(
        640, 360, layout, "", key, 42.0, "rpm", "Cadence",
        cfg_override=cfg, formatted_val="42", history_data=history,
        current_position=1.0,
        target_dt=target,
    )[0]
    reference = render_value_indicator(
        640, 360, layout, "", legacy_key, 42.0, "rpm", "Cadence",
        cfg_override=cfg, formatted_val="42", history_data=prefix,
        current_position=1.0, target_dt=target,
    )[0]
    return np.asarray(optimized), np.asarray(reference), prefix


def test_prefix_matches_naive_reference_at_required_checkpoints():
    history = _history(
        [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10],
        [0.0, 10.0, 20.0, 0.0, 30.0, 40.0, 50.0, 60.0, 70.0, 80.0, 90.0],
    )
    for current in (0.0, 1.0, 2.5, 5.0, 7.5, 9.0, 10.0):
        optimized, reference, prefix = _render_pair(history, current)
        assert np.array_equal(optimized, reference), current
        assert prefix.timestamps[0] == history.timestamps[0]
        assert not any(ts > BASE + timedelta(seconds=current) for ts in prefix.timestamps)


def test_prefix_keeps_zero_and_missing_gap_semantics():
    timestamps = [BASE + timedelta(seconds=value) for value in (0, 1, 2, 3)]
    values = [10.0, 0.0, None, 20.0]
    points = [(float(i), float(i)) for i in range(4)]
    segments = _split_chart_segments(points, timestamps, values)
    assert segments == [[points[0], points[1]], [points[2]], [points[3]]]
    assert _chart_segment_ranges(timestamps, values) == [(0, 2), (2, 3), (3, 4)]
    assert values[1] == 0.0
    assert values[2] is None


def test_prefix_keeps_history_before_and_after_long_gap():
    seconds = [0, 1, 2, 100, 101]
    values = [10.0, 20.0, 30.0, 40.0, 50.0]
    timestamps = [BASE + timedelta(seconds=value) for value in seconds]
    assert _chart_segment_ranges(timestamps, values) == [(0, 3), (3, 5)]
    history = _history(seconds, values)
    for current, expected_count in ((2.5, 3), (50.0, 3), (100.0, 4), (101.0, 5)):
        optimized, reference, prefix = _render_pair(history, current)
        assert np.array_equal(optimized, reference), current
        assert len(prefix) == expected_count
        assert prefix.timestamps[0] == timestamps[0]
        assert prefix.timestamps[-1] <= BASE + timedelta(seconds=current)


def test_cadence_and_hr_use_their_own_timestamps():
    cadence = _history([0, 2, 4, 6], [0.0, 20.0, 0.0, 40.0])
    hr = _history([0, 1, 3, 6], [100.0, 101.0, 102.0, 103.0])
    cfg = _cfg()
    layout = {"global": {"text_outline": 3}, "indicators": {
        "fit_cadence_text": cfg, "fit_heart_rate_text": dict(cfg),
    }}
    for key, history in (("fit_cadence_text", cadence), ("fit_heart_rate_text", hr)):
        target = BASE + timedelta(seconds=3.5)
        image = render_value_indicator(
            640, 360, layout, "", key, 50.0, "", key,
            cfg_override=cfg, formatted_val="50", history_data=history,
            current_position=0.5, target_dt=target,
        )[0]
        assert image is not None
        assert history.timestamps[0] == BASE
        assert history.timestamps[-1] > target
