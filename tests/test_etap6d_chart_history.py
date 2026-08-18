from __future__ import annotations

from datetime import datetime, timedelta, timezone

from src.indicators.chart_builder import ChartHistory, build_chart_data, clip_chart_data
from src.indicators.frame_data import prepare_overlay_frame_data
from src.telemetry_precompute import build_telemetry_cache


BASE = datetime(2026, 8, 18, 4, 46, 25, 700000, tzinfo=timezone.utc)


def series(values: list[float]):
    return [(BASE + timedelta(seconds=i), value) for i, value in enumerate(values)]


def test_clip_chart_history_future_exact_and_before_first():
    samples = series([1.0, 2.0, 3.0, 4.0, 5.0])
    layout = {"indicators": {"fit_heart_rate_text": {"form": "chart", "source": "fit"}}}
    chart = build_chart_data(
        layout,
        lambda source: ([], [], []),
        lambda field, source, key=None: samples,
    )

    middle = clip_chart_data(chart, BASE + timedelta(seconds=2, milliseconds=500), BASE)
    assert middle["fit_heart_rate_text"] == [1.0, 2.0, 3.0]
    assert middle["fit_heart_rate_text"].timestamps[-1] == BASE + timedelta(seconds=2)

    exact = clip_chart_data(chart, BASE + timedelta(seconds=2), BASE)
    assert exact["fit_heart_rate_text"] == [1.0, 2.0, 3.0]

    before = clip_chart_data(chart, BASE - timedelta(microseconds=1), BASE)
    assert before["fit_heart_rate_text"] == []


def test_clip_chart_history_after_last_and_does_not_mutate_source():
    samples = series([0.0, 4.0])
    chart = {"x": ChartHistory([v for _, v in samples], [dt for dt, _ in samples])}
    clipped = clip_chart_data(chart, BASE + timedelta(seconds=99), BASE)
    assert clipped["x"] == [0.0, 4.0]
    assert chart["x"] == [0.0, 4.0]
    assert chart["x"].timestamps == (BASE, BASE + timedelta(seconds=1))


def test_prepare_and_precompute_use_same_clipped_history():
    samples = series([10.0, 20.0, 30.0, 40.0])
    layout = {"indicators": {"fit_heart_rate_text": {"form": "chart", "source": "fit"}}}
    chart = build_chart_data(
        layout,
        lambda source: ([], [], []),
        lambda field, source, key=None: samples,
    )
    target = BASE + timedelta(seconds=1, milliseconds=500)
    prepared = prepare_overlay_frame_data(
        layout=layout,
        target_dt=target,
        tz_offset_hours=0,
        start_dt_utc=BASE,
        speed_samples=[],
        track_samples=[],
        alt_samples=[],
        fit_data={"heart_rate": samples},
        chart_data=chart,
        resolve_cache_value=lambda field, source, dt, key=None: 20.0,
    )
    cached = build_telemetry_cache(
        layout=layout,
        base_dt=target,
        tz_offset_hours=0,
        start_dt_utc=BASE,
        speed_samples=[],
        track_samples=[],
        alt_samples=[],
        fit_data={"heart_rate": samples},
        chart_data=chart,
        total_frames=1,
        resolve_cache_value=lambda field, source, dt, key=None: 20.0,
    ).lookup(0)
    assert prepared["chart_data"]["fit_heart_rate_text"] == [10.0, 20.0]
    assert cached["chart_data"]["fit_heart_rate_text"] == [10.0, 20.0]
