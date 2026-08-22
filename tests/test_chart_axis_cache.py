from datetime import datetime, timedelta

from src.indicators.chart_builder import ChartHistory
from src.indicators.chart_utils import _CHART_AXIS_CACHE, _build_chart_bg


def _history():
    start = datetime(2026, 1, 1)
    timestamps = [start + timedelta(seconds=i) for i in range(3)]
    return ChartHistory([10.0, 20.0, 30.0], timestamps, start, timestamps[-1])


def _build(history, **overrides):
    options = {
        "width": 160, "height": 70, "line_color": (255, 0, 0),
        "line_thickness": 2, "fill_alpha": 40, "fill_color": (255, 0, 0),
        "show_axes": True, "grid_color": (68, 68, 68, 60),
        "time_labels": ["-60 s", "-30 s", "0 s"], "value_labels": None,
        "supersample": 1, "custom_min_val": 0.0, "custom_max_val": 100.0,
        "label_count": 2, "label_units": False, "unit": "BPM",
        "show_average": False, "label_font_size": 0, "font_path": "",
    }
    options.update(overrides)
    return _build_chart_bg(history_values=history, draw_series=False, **options)


def test_axis_cache_same_key_hits_and_static_properties_invalidate():
    history = _history()
    _CHART_AXIS_CACHE.clear()
    _build(history)
    assert len(_CHART_AXIS_CACHE) == 1
    _build(history)
    assert len(_CHART_AXIS_CACHE) == 1

    for change, invalidates in (
        ({"width": 161}, True), ({"height": 71}, True), ({"supersample": 2}, True),
        ({"font_path": "assets/Roboto-Bold.ttf"}, True), ({"label_font_size": 12}, True),
        ({"grid_color": (80, 80, 80, 60)}, True),
        ({"time_labels": ["-30 s", "-15 s", "0 s"]}, True),
        ({"value_labels": ["0", "90"]}, True),
        ({"custom_min_val": 20.0, "custom_max_val": 120.0}, True),
        ({"show_axes": False}, True), ({"label_units": True}, True),
        ({"unit": "rpm"}, False),
    ):
        _CHART_AXIS_CACHE.clear()
        _build(history)
        before = len(_CHART_AXIS_CACHE)
        _build(history, **change)
        assert before == 1
        assert len(_CHART_AXIS_CACHE) == (2 if invalidates else 1)


def test_hr_and_cadence_axis_ranges_use_separate_entries():
    history = _history()
    _CHART_AXIS_CACHE.clear()
    _build(history, custom_min_val=40.0, custom_max_val=220.0, unit="BPM")
    _build(history, custom_min_val=0.0, custom_max_val=200.0, unit="rpm")
    assert len(_CHART_AXIS_CACHE) == 2
