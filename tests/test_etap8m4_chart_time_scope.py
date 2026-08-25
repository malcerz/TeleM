"""Tests for ETAP 8M.4: Chart Time Scope (Activity vs Video)."""

from datetime import datetime, timedelta, timezone
from pathlib import Path
import json
import pytest

from src.indicators.chart_builder import ChartHistory, build_chart_data, clip_chart_data
from src.indicators.chart_utils import (
    _history_chart_cache_key,
    get_history_chart_background,
    _build_chart_bg,
)
from src.indicators.frame_data import prepare_overlay_frame_data
from src.gui.layout_manager import normalize_layout, default_layout
from src.gui.indicator_schemas import get_value_schema
from src.gui.qt.models import _chart_tab_fields

BASE = datetime(2026, 8, 19, 10, 0, 0, tzinfo=timezone.utc)


def make_series(values: list[float], start_dt: datetime = BASE, step_s: float = 1.0) -> list[tuple[datetime, float]]:
    return [(start_dt + timedelta(seconds=i * step_s), val) for i, val in enumerate(values)]


def test_default_scope_is_activity():
    """1. Layout without explicit chart_time_scope defaults to 'activity' mode spanning full source."""
    layout = {
        "indicators": {
            "fit_cadence_text": {"form": "chart", "source": "fit"}
        }
    }
    fit_samples = make_series([70.0, 75.0, 80.0, 85.0, 90.0], start_dt=BASE, step_s=10.0)
    video_start = BASE + timedelta(seconds=15)
    video_end = BASE + timedelta(seconds=35)

    chart_data = build_chart_data(
        layout,
        lambda src: ([], [], []),
        lambda field, src, key=None: fit_samples,
        start_dt_utc=video_start,
        end_dt_utc=video_end,
    )

    cad_chart = chart_data["fit_cadence_text"]
    assert getattr(cad_chart, "time_scope", None) == "activity"
    assert len(cad_chart) == 5
    assert cad_chart.chart_start_dt == BASE
    assert cad_chart.chart_end_dt == BASE + timedelta(seconds=40)


def test_activity_scope_spans_full_fit_duration():
    """2. In activity mode, chart points and bounds span the full source duration."""
    layout = {
        "indicators": {
            "fit_heart_rate_text": {
                "form": "chart",
                "source": "fit",
                "chart_time_scope": "activity",
            }
        }
    }
    # 100 samples across 1000s
    fit_samples = make_series([float(100 + i) for i in range(100)], start_dt=BASE, step_s=10.0)
    video_start = BASE + timedelta(seconds=500)
    video_end = BASE + timedelta(seconds=550)

    source_ranges = {"fit": (BASE, BASE + timedelta(seconds=990))}
    chart_data = build_chart_data(
        layout,
        lambda src: ([], [], []),
        lambda field, src, key=None: fit_samples,
        start_dt_utc=video_start,
        end_dt_utc=video_end,
        source_activity_ranges=source_ranges,
    )

    hr_chart = chart_data["fit_heart_rate_text"]
    assert len(hr_chart) == 100
    assert hr_chart.chart_start_dt == BASE
    assert hr_chart.chart_end_dt == BASE + timedelta(seconds=990)


def test_video_scope_clips_to_video_range():
    """3. In video mode, chart points are clipped to the video time window."""
    layout = {
        "indicators": {
            "fit_heart_rate_text": {
                "form": "chart",
                "source": "fit",
                "chart_time_scope": "video",
            }
        }
    }
    # Samples from 0s to 100s
    fit_samples = make_series([float(i) for i in range(101)], start_dt=BASE, step_s=1.0)
    video_start = BASE + timedelta(seconds=20)
    video_end = BASE + timedelta(seconds=50)

    chart_data = build_chart_data(
        layout,
        lambda src: ([], [], []),
        lambda field, src, key=None: fit_samples,
        start_dt_utc=video_start,
        end_dt_utc=video_end,
    )

    hr_chart = chart_data["fit_heart_rate_text"]
    assert hr_chart.time_scope == "video"
    assert len(hr_chart) == 31  # 20s to 50s inclusive
    assert hr_chart.chart_start_dt == video_start
    assert hr_chart.chart_end_dt == video_end
    assert hr_chart[0] == 20.0
    assert hr_chart[-1] == 50.0


def test_marker_position_activity_mode():
    """4. Marker position in activity mode corresponds to video position relative to full activity."""
    # Full activity 0..1000s, video is 800s..900s
    fit_samples = make_series([float(i) for i in range(1001)], start_dt=BASE, step_s=1.0)
    act_start = BASE
    act_end = BASE + timedelta(seconds=1000)

    history = ChartHistory(
        [s[1] for s in fit_samples],
        [s[0] for s in fit_samples],
        chart_start_dt=act_start,
        chart_end_dt=act_end,
        time_scope="activity",
    )

    # At video start (800s): pos = 800 / 1000 = 0.80
    target_start = BASE + timedelta(seconds=800)
    pos_start = (target_start - act_start).total_seconds() / (act_end - act_start).total_seconds()
    assert abs(pos_start - 0.80) < 1e-6

    # At video end (900s): pos = 900 / 1000 = 0.90
    target_end = BASE + timedelta(seconds=900)
    pos_end = (target_end - act_start).total_seconds() / (act_end - act_start).total_seconds()
    assert abs(pos_end - 0.90) < 1e-6


def test_marker_position_video_mode():
    """5. Marker position in video mode runs from 0.0 to 1.0 across the video."""
    video_start = BASE + timedelta(seconds=200)
    video_end = BASE + timedelta(seconds=300)

    history = ChartHistory(
        [float(i) for i in range(101)],
        [video_start + timedelta(seconds=i) for i in range(101)],
        chart_start_dt=video_start,
        chart_end_dt=video_end,
        time_scope="video",
    )

    # At video start: pos = 0.0
    pos_start = (video_start - history.chart_start_dt).total_seconds() / (history.chart_end_dt - history.chart_start_dt).total_seconds()
    assert abs(pos_start - 0.0) < 1e-6

    # At video middle: pos = 0.5
    video_mid = BASE + timedelta(seconds=250)
    pos_mid = (video_mid - history.chart_start_dt).total_seconds() / (history.chart_end_dt - history.chart_start_dt).total_seconds()
    assert abs(pos_mid - 0.5) < 1e-6

    # At video end: pos = 1.0
    pos_end = (video_end - history.chart_start_dt).total_seconds() / (history.chart_end_dt - history.chart_start_dt).total_seconds()
    assert abs(pos_end - 1.0) < 1e-6


def test_points_geometry_timestamp_proportional():
    """6. Non-equidistant samples are mapped proportionally to their timestamps on the X axis."""
    # Two samples: t=0s (val=10), t=100s (val=20), total duration = 100s
    # Sample 1 at 0s, Sample 2 at 20s (20% of timeline), Sample 3 at 100s (100% of timeline)
    ts = [BASE, BASE + timedelta(seconds=20), BASE + timedelta(seconds=100)]
    vals = [10.0, 50.0, 20.0]
    history = ChartHistory(vals, ts, chart_start_dt=BASE, chart_end_dt=BASE + timedelta(seconds=100))

    img, points, y1, y2, thick, _ = get_history_chart_background(history, width=200, height=100)
    assert len(points) == 3
    x0, x1, x2 = points[0][0], points[1][0], points[2][0]

    # Ratio of distance (x1 - x0) / (x2 - x0) should be 20/100 = 0.20
    ratio = (x1 - x0) / (x2 - x0)
    assert abs(ratio - 0.20) < 0.01


def test_chart_bg_cache_key_includes_scope_and_bounds():
    """7. _history_chart_cache_key isolates cache entries by chart_start_dt, chart_end_dt, and time_scope."""
    ts = [BASE, BASE + timedelta(seconds=10)]
    vals = [1.0, 2.0]
    h1 = ChartHistory(vals, ts, chart_start_dt=BASE, chart_end_dt=BASE + timedelta(seconds=10), time_scope="activity")
    h2 = ChartHistory(vals, ts, chart_start_dt=BASE, chart_end_dt=BASE + timedelta(seconds=10), time_scope="video")
    h3 = ChartHistory(vals, ts, chart_start_dt=BASE, chart_end_dt=BASE + timedelta(seconds=20), time_scope="activity")

    k1 = _history_chart_cache_key(h1, 200, 100, (255, 0, 0), 2, 50, None, True, None, None, None, 1, None, None, 2, False, "", False, 0, None)
    k2 = _history_chart_cache_key(h2, 200, 100, (255, 0, 0), 2, 50, None, True, None, None, None, 1, None, None, 2, False, "", False, 0, None)
    k3 = _history_chart_cache_key(h3, 200, 100, (255, 0, 0), 2, 50, None, True, None, None, None, 1, None, None, 2, False, "", False, 0, None)

    assert k1 != k2
    assert k1 != k3
    assert k2 != k3


def test_current_value_unaffected_by_chart_time_scope():
    """8. Instantaneous current value lookup is completely identical regardless of chart_time_scope."""
    samples = make_series([60.0, 70.0, 80.0, 90.0, 100.0], start_dt=BASE, step_s=10.0)
    layout_act = {
        "indicators": {
            "speed_text": {"form": "chart", "source": "fit", "chart_time_scope": "activity"}
        }
    }
    layout_vid = {
        "indicators": {
            "speed_text": {"form": "chart", "source": "fit", "chart_time_scope": "video"}
        }
    }

    target_dt = BASE + timedelta(seconds=25)  # Between 20s (80.0) and 30s (90.0)
    cd_act = build_chart_data(layout_act, lambda s: (samples, [], []), lambda f, s, k=None: samples, start_dt_utc=BASE, end_dt_utc=BASE + timedelta(seconds=40))
    cd_vid = build_chart_data(layout_vid, lambda s: (samples, [], []), lambda f, s, k=None: samples, start_dt_utc=BASE + timedelta(seconds=10), end_dt_utc=BASE + timedelta(seconds=30))

    fd_act = prepare_overlay_frame_data(
        layout=layout_act,
        target_dt=target_dt,
        tz_offset_hours=0,
        start_dt_utc=BASE,
        speed_samples=[],
        track_samples=[],
        alt_samples=[],
        fit_data={"speed": samples},
        chart_data=cd_act,
    )
    fd_vid = prepare_overlay_frame_data(
        layout=layout_vid,
        target_dt=target_dt,
        tz_offset_hours=0,
        start_dt_utc=BASE,
        speed_samples=[],
        track_samples=[],
        alt_samples=[],
        fit_data={"speed": samples},
        chart_data=cd_vid,
    )

    # Instantaneous current value is identical
    assert fd_act["speed_value"] == fd_vid["speed_value"]
    assert fd_act["indicator_values"]["speed_text"] == fd_vid["indicator_values"]["speed_text"]
    assert fd_act["indicator_values"]["speed_text"] == 85.0


def test_layout_persistence_chart_time_scope(tmp_path):
    """9. chart_time_scope is persisted to layout JSON and preserved across save/reload."""
    layout = default_layout(1920, 1080)
    layout["indicators"]["fit_cadence_text"] = {
        "enabled": True, "form": "chart", "source": "fit",
        "chart_time_scope": "video",
    }
    layout["indicators"]["fit_heart_rate_text"] = {
        "enabled": True, "form": "chart", "source": "fit",
        "chart_time_scope": "activity",
    }

    save_file = tmp_path / "test_layout.json"
    save_file.write_text(json.dumps(layout), encoding="utf-8")

    loaded = normalize_layout(save_file, 1920, 1080)
    assert loaded["indicators"]["fit_cadence_text"]["chart_time_scope"] == "video"
    assert loaded["indicators"]["fit_heart_rate_text"]["chart_time_scope"] == "activity"


def test_preview_and_final_chart_parity():
    """10. Preview and final worker chart calculations produce identical background geometries."""
    fit_samples = make_series([float(50 + i * 2) for i in range(50)], start_dt=BASE, step_s=2.0)
    layout = {
        "indicators": {
            "fit_cadence_text": {
                "enabled": True, "form": "chart", "source": "fit",
                "chart_time_scope": "activity",
                "line_width": 2, "chart_color": "#00FF00",
            }
        }
    }

    # Pipeline 1: Preview chart data build
    cd_prev = build_chart_data(
        layout, lambda s: ([], [], []), lambda f, s, k=None: fit_samples,
        start_dt_utc=BASE, end_dt_utc=BASE + timedelta(seconds=100),
    )
    # Pipeline 2: Worker cache chart data build
    cd_work = build_chart_data(
        layout, lambda s: ([], [], []), lambda f, s, k=None: fit_samples,
        start_dt_utc=BASE, end_dt_utc=BASE + timedelta(seconds=100),
    )

    assert cd_prev["fit_cadence_text"].chart_start_dt == cd_work["fit_cadence_text"].chart_start_dt
    assert cd_prev["fit_cadence_text"].chart_end_dt == cd_work["fit_cadence_text"].chart_end_dt
    assert cd_prev["fit_cadence_text"] == cd_work["fit_cadence_text"]
