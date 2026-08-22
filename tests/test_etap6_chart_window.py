"""ETAP 6 tests for moving chart history windows."""

from datetime import datetime, timedelta, timezone

from src.indicators.chart import _window_time_labels
from src.indicators.chart_builder import (
    build_chart_data,
    clip_chart_data_for_target,
    normalize_chart_window_s,
)
from src.indicators.dispatcher import render_value_indicator
from src.indicators.frame_data import prepare_overlay_frame_data


BASE = datetime(2026, 8, 19, 10, 0, 0, tzinfo=timezone.utc)


def _samples(start_s: int = 0, end_s: int = 200):
    return [
        (BASE + timedelta(seconds=i), float(i))
        for i in range(start_s, end_s + 1)
    ]


def _window_layout(window_s=60):
    return {
        "indicators": {
            "fit_heart_rate_text": {
                "enabled": True,
                "form": "chart",
                "source": "fit",
                "chart_time_scope": "window",
                "chart_window_s": window_s,
            }
        }
    }


def _build_window_chart(window_s=60):
    samples = _samples()
    chart = build_chart_data(
        _window_layout(window_s),
        lambda _source: ([], [], []),
        lambda _field, _source, _key=None: samples,
        start_dt_utc=BASE,
        end_dt_utc=BASE + timedelta(seconds=200),
    )
    return samples, chart


def test_window_60_seconds_uses_only_current_history():
    samples, chart = _build_window_chart(60)
    current = BASE + timedelta(seconds=180)
    clipped = clip_chart_data_for_target(chart, current)["fit_heart_rate_text"]

    assert clipped == [float(i) for i in range(120, 181)]
    assert clipped.timestamps[0] == BASE + timedelta(seconds=120)
    assert clipped.timestamps[-1] == current
    assert clipped.chart_start_dt == BASE + timedelta(seconds=120)
    assert clipped.chart_end_dt == current
    assert max(clipped.timestamps) <= current
    assert len(samples) == 201  # source history remains untouched


def test_window_at_activity_start_does_not_stretch_before_first_sample():
    _samples_all, chart = _build_window_chart(60)
    current = BASE + timedelta(seconds=20)
    clipped = clip_chart_data_for_target(chart, current)["fit_heart_rate_text"]

    assert clipped == [float(i) for i in range(0, 21)]
    assert clipped.chart_start_dt == BASE
    assert clipped.chart_end_dt == current


def test_window_never_exposes_future_samples():
    _samples_all, chart = _build_window_chart(60)
    current = BASE + timedelta(seconds=180)
    clipped = clip_chart_data_for_target(chart, current)["fit_heart_rate_text"]

    assert all(dt <= current for dt in clipped.timestamps)
    assert clipped[-1] == 180.0


def test_activity_and_video_are_unchanged_by_window_clipper():
    samples = _samples()
    for scope in ("activity", "video"):
        layout = {
            "indicators": {
                "fit_heart_rate_text": {
                    "form": "chart", "source": "fit",
                    "chart_time_scope": scope, "chart_window_s": 60,
                }
            }
        }
        chart = build_chart_data(
            layout, lambda _source: ([], [], []),
            lambda _field, _source, _key=None: samples,
            start_dt_utc=BASE,
            end_dt_utc=BASE + timedelta(seconds=200),
        )
        result = clip_chart_data_for_target(chart, BASE + timedelta(seconds=180))
        assert result is chart
        assert result["fit_heart_rate_text"] == chart["fit_heart_rate_text"]


def test_invalid_window_values_are_safe_and_bounded():
    assert normalize_chart_window_s(0) == 60.0
    assert normalize_chart_window_s(-10) == 60.0
    assert normalize_chart_window_s(None) == 60.0
    assert normalize_chart_window_s("not-a-number") == 60.0
    assert normalize_chart_window_s(99999) == 600.0


def test_window_render_has_relative_axis_and_stays_inside_bbox():
    _samples_all, chart = _build_window_chart(60)
    current = BASE + timedelta(seconds=180)
    clipped = clip_chart_data_for_target(chart, current)["fit_heart_rate_text"]
    cfg = dict(_window_layout(60)["indicators"]["fit_heart_rate_text"])
    cfg.update({
        "label": "HEART RATE", "x": 50.0, "y": 50.0,
        "font_size": 1.2, "size": 27.0, "min_val": 0.0,
        "max_val": 220.0, "unit": "BPM", "show_value": True,
        "show_units": True,
    })
    layout = {"global": {}, "indicators": {"fit_heart_rate_text": cfg}}
    img, _rx, _ry, _extra = render_value_indicator(
        canvas_w=1920, canvas_h=1080,
        layout=layout, font_path="assets/Roboto-Bold.ttf",
        key="fit_heart_rate_text", value=180.0, unit="BPM",
        label="HEART RATE", cfg_override=cfg,
        history_data=clipped, target_dt=current,
    )

    assert img is not None
    bbox = img.getchannel("A").getbbox()
    assert bbox is not None
    assert 0 <= bbox[0] < bbox[2] <= img.width
    assert 0 <= bbox[1] < bbox[3] <= img.height
    assert _window_time_labels(60) == ["-60 s", "-45 s", "-30 s", "-15 s", "0 s"]


def test_preview_frame_data_uses_the_same_window_semantics_for_cadence_and_hr():
    samples = _samples()
    layout = {
        "indicators": {
            "fit_cadence_text": {
                "form": "chart", "source": "fit",
                "chart_time_scope": "window", "chart_window_s": 60,
            },
            "fit_heart_rate_text": {
                "form": "chart", "source": "fit",
                "chart_time_scope": "window", "chart_window_s": 60,
            },
        }
    }
    chart = build_chart_data(
        layout, lambda _source: ([], [], []),
        lambda _field, _source, _key=None: samples,
        start_dt_utc=BASE, end_dt_utc=BASE + timedelta(seconds=200),
    )
    current = BASE + timedelta(seconds=180)
    frame = prepare_overlay_frame_data(
        layout=layout, target_dt=current, tz_offset_hours=0,
        start_dt_utc=BASE, speed_samples=[], track_samples=[], alt_samples=[],
        fit_data={"cadence": samples, "heart_rate": samples},
        chart_data=chart,
    )

    for key in ("fit_cadence_text", "fit_heart_rate_text"):
        history = frame["chart_data"][key]
        assert history.chart_start_dt == BASE + timedelta(seconds=120)
        assert history.chart_end_dt == current
        assert len(history) == 61
        assert history.timestamps[-1] == current
