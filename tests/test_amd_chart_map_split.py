"""ETAP 7B regression coverage for AMD semantic/compositing layout roles."""

from datetime import datetime, timedelta, timezone

from src.ffmpeg.amd_native_exporter import _amd_layout_roles
from src.ffmpeg.worker_cache import WORKER_CACHE, _resolve_cache_value, init_worker
from src.indicators.frame_data import build_active_fit_field_plan
from src.telemetry_precompute import build_telemetry_cache


BASE = datetime(2026, 8, 18, 4, 48, 25, tzinfo=timezone.utc)
CHART_KEYS = ("fit_cadence_text", "fit_heart_rate_text")


def _after_map_layout():
    chart_cfg = {
        "enabled": True,
        "form": "chart",
        "source": "fit",
        "chart_time_scope": "window",
        "chart_window_s": 60,
    }
    return {
        "indicators": {
            "time_display": {"enabled": True, "form": "time_display"},
            "track_map": {"enabled": True, "form": "map"},
            "fit_cadence_text": dict(chart_cfg),
            "fit_heart_rate_text": dict(chart_cfg),
        }
    }


def _fit_samples():
    return {
        "cadence": [(BASE + timedelta(seconds=i), float(80 + i)) for i in range(121)],
        "heart_rate": [(BASE + timedelta(seconds=i), float(140 + i)) for i in range(121)],
    }


def test_after_map_charts_use_full_semantic_layout_for_precompute():
    layout = _after_map_layout()
    semantic, below, above, after = _amd_layout_roles(layout, gpu_map_enabled=True)

    assert semantic is layout
    assert list(below["indicators"]) == ["time_display"]
    assert list(above["indicators"]) == list(CHART_KEYS)
    assert after == list(CHART_KEYS)

    fit_data = _fit_samples()
    init_worker(
        video_width=1280,
        video_height=720,
        font_path="",
        layout=semantic,
        field_samples={},
        fit_data=fit_data,
        start_dt_utc=BASE,
        target_fps=1.0,
        total_overlay_frames=121,
    )

    chart_data = WORKER_CACHE["_precomputed_chart_data"]
    assert set(CHART_KEYS).issubset(chart_data)
    for key in CHART_KEYS:
        history = chart_data[key]
        assert history.time_scope == "window"
        assert history.window_s == 60.0
        assert history.chart_start_dt == BASE
        assert history.chart_end_dt == BASE + timedelta(seconds=120)

    fit_field_plan = build_active_fit_field_plan(layout, fit_data.keys())
    cache = build_telemetry_cache(
        layout=semantic,
        base_dt=BASE,
        tz_offset_hours=0.0,
        start_dt_utc=BASE,
        speed_samples=[],
        track_samples=[],
        alt_samples=[],
        fit_data=fit_data,
        chart_data=chart_data,
        resolve_cache_value=_resolve_cache_value,
        fit_field_plan=fit_field_plan,
        total_frames=121,
        target_fps=1.0,
    )

    frame = cache.lookup(120)
    for key in CHART_KEYS:
        history = frame["chart_data"][key]
        assert history.time_scope == "window"
        assert history.window_s == 60.0
        assert history.chart_start_dt == BASE + timedelta(seconds=60)
        assert history.chart_end_dt == BASE + timedelta(seconds=120)
        assert len(history) == 61
        assert history.timestamps[0] == BASE + timedelta(seconds=60)
        assert history.timestamps[-1] == BASE + timedelta(seconds=120)
        assert all(timestamp <= BASE + timedelta(seconds=120) for timestamp in history.timestamps)


def test_before_map_and_no_map_keep_their_existing_compositing_partitions():
    layout = _after_map_layout()
    indicators = layout["indicators"]
    reordered = {key: indicators[key] for key in ("time_display", *CHART_KEYS, "track_map")}
    layout["indicators"] = reordered

    _semantic, below, above, after = _amd_layout_roles(layout, gpu_map_enabled=True)
    assert list(below["indicators"]) == ["time_display", *CHART_KEYS]
    assert above["indicators"] == {}
    assert after == []

    no_map = {"indicators": {key: cfg for key, cfg in indicators.items() if key != "track_map"}}
    _semantic, no_map_compose, no_map_above, no_map_after = _amd_layout_roles(
        no_map, gpu_map_enabled=True,
    )
    assert no_map_compose is no_map
    assert no_map_above is None
    assert no_map_after == []


def test_disabled_track_map_does_not_activate_ordered_compositing_split():
    layout = _after_map_layout()
    layout["indicators"]["track_map"]["enabled"] = False

    semantic, compose, above, after = _amd_layout_roles(layout, gpu_map_enabled=True)
    assert semantic is layout
    assert compose is layout
    assert above is None
    assert after == []
