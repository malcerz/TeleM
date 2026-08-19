from __future__ import annotations

from datetime import datetime, timedelta, timezone

from src.indicators.chart_builder import ChartHistory, build_chart_data, clip_chart_data
from src.indicators.chart import _render_chart_indicator
from src.indicators.dispatcher import render_value_indicator
from src.indicators.frame_data import prepare_overlay_frame_data
from src.telemetry_precompute import build_telemetry_cache
from src.telemetry_extract import _interpolate_step


BASE = datetime(2026, 8, 18, 4, 46, 25, 700000, tzinfo=timezone.utc)


def series(values: list[float], start: datetime = BASE, step_s: float = 1.0):
    return [(start + timedelta(seconds=i * step_s), value) for i, value in enumerate(values)]


def test_etap8e_section39_full_series_invariant():
    """Requirement 39: Full chart series invariant across different target_dt values."""
    # 10 samples: t0 .. t9
    samples = series([10.0, 20.0, 30.0, 40.0, 50.0, 60.0, 70.0, 80.0, 90.0, 100.0])
    layout = {"indicators": {"fit_heart_rate_text": {"form": "chart", "source": "fit"}}}
    chart = build_chart_data(
        layout,
        lambda source: ([], [], []),
        lambda field, source, key=None: samples,
        start_dt_utc=BASE,
        end_dt_utc=BASE + timedelta(seconds=9),
    )

    targets = [
        BASE,
        BASE + timedelta(seconds=3),
        BASE + timedelta(seconds=7),
        BASE + timedelta(seconds=9),
    ]

    expected_values = [10.0, 20.0, 30.0, 40.0, 50.0, 60.0, 70.0, 80.0, 90.0, 100.0]

    for target in targets:
        prep = prepare_overlay_frame_data(
            layout=layout,
            target_dt=target,
            tz_offset_hours=0,
            start_dt_utc=BASE,
            speed_samples=[],
            track_samples=[],
            alt_samples=[],
            fit_data={"heart_rate": samples},
            chart_data=chart,
            resolve_cache_value=lambda field, source, dt, key=None: 50.0,
        )
        assert prep["chart_data"]["fit_heart_rate_text"] == expected_values
        assert len(prep["chart_data"]["fit_heart_rate_text"]) == 10
        assert prep["chart_data"]["fit_heart_rate_text"].timestamps[0] == BASE
        assert prep["chart_data"]["fit_heart_rate_text"].timestamps[-1] == BASE + timedelta(seconds=9)


def test_etap8e_section40_marker_position():
    """Requirement 40: Marker position advances correctly from 0.0 to 1.0."""
    samples = series([10.0, 20.0, 30.0, 40.0, 50.0, 60.0, 70.0, 80.0, 90.0, 100.0])
    layout = {"indicators": {"fit_heart_rate_text": {"form": "chart", "source": "fit"}}}
    chart = build_chart_data(
        layout,
        lambda source: ([], [], []),
        lambda field, source, key=None: samples,
        start_dt_utc=BASE,
        end_dt_utc=BASE + timedelta(seconds=9),
    )

    history = chart["fit_heart_rate_text"]
    t_start = history.timestamps[0]
    t_end = history.timestamps[-1]

    # Test t0 -> pos = 0.0
    t0 = BASE
    pos_t0 = (t0 - t_start).total_seconds() / (t_end - t_start).total_seconds()
    assert abs(pos_t0 - 0.0) < 1e-6

    # Test middle (t = 4.5s) -> pos = 0.5
    t_mid = BASE + timedelta(seconds=4, milliseconds=500)
    pos_mid = (t_mid - t_start).total_seconds() / (t_end - t_start).total_seconds()
    assert abs(pos_mid - 0.5) < 1e-6

    # Test t9 -> pos = 1.0
    t9 = BASE + timedelta(seconds=9)
    pos_t9 = (t9 - t_start).total_seconds() / (t_end - t_start).total_seconds()
    assert abs(pos_t9 - 1.0) < 1e-6


def test_etap8e_section41_video_range_clipping():
    """Requirement 41: Samples outside video bounds [-10s, +190s vs video 0s..180s] are excluded from chart."""
    # Source data from -10s to +190s (201 samples)
    source_start = BASE - timedelta(seconds=10)
    samples = series([float(i) for i in range(201)], start=source_start, step_s=1.0)

    video_start = BASE
    video_end = BASE + timedelta(seconds=180)

    layout = {"indicators": {"fit_heart_rate_text": {"form": "chart", "source": "fit", "chart_time_scope": "video"}}}
    chart = build_chart_data(
        layout,
        lambda source: ([], [], []),
        lambda field, source, key=None: samples,
        start_dt_utc=video_start,
        end_dt_utc=video_end,
    )

    hr_chart = chart["fit_heart_rate_text"]
    assert hr_chart.timestamps[0] == video_start
    assert hr_chart.timestamps[-1] == video_end
    # 0s to 180s inclusive is 181 samples
    assert len(hr_chart) == 181
    # First sample value should be 10.0 (corresponding to t=0s, which is 10s after source_start)
    assert hr_chart[0] == 10.0
    # Last sample value should be 190.0 (corresponding to t=180s, which is 190s after source_start)
    assert hr_chart[-1] == 190.0


def test_etap8e_section42_no_future_effect_on_current_value():
    """Requirement 42: Future samples visible on chart do NOT affect current lookup value."""
    # Samples: at t=0s val=50, at t=1s val=50, at t=2s (future) val=999
    samples = [
        (BASE, 50.0),
        (BASE + timedelta(seconds=1), 50.0),
        (BASE + timedelta(seconds=2), 999.0),
    ]
    layout = {"indicators": {"fit_heart_rate_text": {"form": "chart", "source": "fit"}}}
    chart = build_chart_data(
        layout,
        lambda source: ([], [], []),
        lambda field, source, key=None: samples,
        start_dt_utc=BASE,
        end_dt_utc=BASE + timedelta(seconds=2),
    )

    # Chart displays all 3 points (including future 999.0)
    assert chart["fit_heart_rate_text"] == [50.0, 50.0, 999.0]

    # Current value at target = BASE + 1.0s MUST be 50.0 (STEP contract, ignoring future 999.0)
    target = BASE + timedelta(seconds=1)
    current_val = _interpolate_step(samples, target)
    assert current_val == 50.0

    # Also at target = BASE + 1.5s (between 1s and 2s)
    target_mid = BASE + timedelta(seconds=1, milliseconds=500)
    current_val_mid = _interpolate_step(samples, target_mid)
    assert current_val_mid == 50.0
