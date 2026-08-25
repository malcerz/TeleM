from __future__ import annotations

from datetime import datetime, timedelta, timezone

from src.ffmpeg.worker_cache import WORKER_CACHE, _resolve_cache_value
from src.gui.telemetry_manager import TelemetryDataManager
from src.indicators.chart_builder import build_chart_data
from src.indicators.frame_data import (
    build_active_fit_field_plan,
    prepare_overlay_frame_data,
)
from src.telemetry_extract import interpolate_value
from src.telemetry_precompute import build_telemetry_cache


BASE = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)


def samples(value: float):
    return [(BASE, value), (BASE + timedelta(seconds=1), value)]


def manager_with_sources() -> TelemetryDataManager:
    m = TelemetryDataManager(interpolate_fn=interpolate_value)
    m.speed_samples = samples(10.0)
    m.fit_data = {"speed": samples(20.0), "K1": samples(7.0)}
    m.gpx_speed_samples = samples(30.0)
    return m


def test_precompute_empty_fit_does_not_fallback_to_gpmf():
    layout = {"indicators": {"speed_visual": {"enabled": True, "source": "fit"}}}
    cache = build_telemetry_cache(
        layout=layout, base_dt=BASE.replace(tzinfo=None), tz_offset_hours=0,
        start_dt_utc=BASE.replace(tzinfo=None), speed_samples=samples(10.0),
        track_samples=[], alt_samples=[], fit_data={}, total_frames=1,
        resolve_cache_value=lambda *_args: None,
    )
    assert cache.lookup(0)["speed_value"] is None


def test_precompute_empty_gpx_does_not_fallback_to_gpmf():
    layout = {"indicators": {"speed_visual": {"enabled": True, "source": "gpx"}}}
    cache = build_telemetry_cache(
        layout=layout, base_dt=BASE.replace(tzinfo=None), tz_offset_hours=0,
        start_dt_utc=BASE.replace(tzinfo=None), speed_samples=samples(10.0),
        track_samples=[], alt_samples=[], gpx_speed_samples=[], total_frames=1,
        resolve_cache_value=lambda *_args: None,
    )
    assert cache.lookup(0)["speed_value"] is None


def test_missing_and_real_zero_are_distinct_in_all_value_paths():
    layout = {"indicators": {"speed_visual": {"enabled": True, "source": "fit"}}}
    empty = manager_with_sources()
    empty.fit_data = {}
    assert empty.resolve_value("speed", BASE, source="fit") is None
    frame = prepare_overlay_frame_data(
        layout=layout, target_dt=BASE, tz_offset_hours=0,
        start_dt_utc=BASE, speed_samples=samples(10.0), track_samples=[],
        alt_samples=[], fit_data={}, resolve_cache_value=lambda *_args: None,
    )
    assert frame["speed_value"] is None

    zero = manager_with_sources()
    zero.fit_data = {"speed": samples(0.0)}
    assert zero.resolve_value("speed", BASE, source="fit") == 0.0
    zero_cache = build_telemetry_cache(
        layout=layout, base_dt=BASE.replace(tzinfo=None), tz_offset_hours=0,
        start_dt_utc=BASE.replace(tzinfo=None), speed_samples=samples(10.0),
        track_samples=[], alt_samples=[], fit_data={"speed": samples(0.0)},
        total_frames=1, resolve_cache_value=zero.resolve_value,
    )
    assert zero_cache.lookup(0)["speed_value"] == 0.0


def test_source_round_trip_is_strict_for_manager_chart_precompute_worker(monkeypatch):
    m = manager_with_sources()
    layout = {"indicators": {"speed_text": {"form": "chart", "source": "gpmf"}}}
    for source, expected in (("gpmf", 10.0), ("fit", 20.0), ("gpx", 30.0), ("gpmf", 10.0)):
        layout["indicators"]["speed_text"]["source"] = source
        assert m.resolve_value("speed", BASE, source=source) == expected
        chart = build_chart_data(
            layout, m.get_samples_for_source,
            lambda field, src, key=None: m.resolve_samples(field, src, key),
        )
        assert chart["speed_text"] == [expected, expected]
        cache = build_telemetry_cache(
            layout=layout, base_dt=BASE.replace(tzinfo=None), tz_offset_hours=0,
            start_dt_utc=BASE.replace(tzinfo=None), speed_samples=m.speed_samples,
            track_samples=[], alt_samples=[], fit_data=m.fit_data,
            gpx_speed_samples=m.gpx_speed_samples, total_frames=1,
            resolve_cache_value=m.resolve_value,
        )
        assert cache.lookup(0)["speed_value"] == expected

    monkeypatch.setitem(WORKER_CACHE, "field_samples", {"speed_samples": samples(10.0)})
    monkeypatch.setitem(WORKER_CACHE, "fit_data", {"speed": samples(20.0)})
    monkeypatch.setitem(WORKER_CACHE, "gpx_speed_samples", samples(30.0))
    assert _resolve_cache_value("speed", "gpmf", BASE) == 10.0
    assert _resolve_cache_value("speed", "fit", BASE) == 20.0
    assert _resolve_cache_value("speed", "gpx", BASE) == 30.0


def test_dynamic_fit_plan_tracks_current_file_without_mutating_layout():
    layout = {
        "indicators": {
            "fit_K1_text": {"enabled": True, "form": "text"},
            "fit_K2_text": {"enabled": True, "form": "text"},
        }
    }
    plan_a = build_active_fit_field_plan(layout, {"K1"})
    assert plan_a["active_fit_fields"] == ["K1"]
    assert plan_a["active_fit_fields_missing_samples"] == ["K2"]
    assert "fit_K2_text" in layout["indicators"]

    plan_b = build_active_fit_field_plan(layout, {"K2"})
    assert plan_b["active_fit_fields"] == ["K2"]
    assert plan_b["active_fit_fields_missing_samples"] == ["K1"]
    assert set(layout["indicators"]) == {"fit_K1_text", "fit_K2_text"}


def test_frame_data_keeps_configured_missing_fit_field_as_none():
    layout = {"indicators": {"fit_K1_text": {"enabled": True, "source": "fit"}}}
    data = prepare_overlay_frame_data(
        layout=layout, target_dt=BASE, tz_offset_hours=0,
        start_dt_utc=BASE, speed_samples=[], track_samples=[], alt_samples=[],
        fit_data={}, resolve_cache_value=lambda *_args: None,
        fit_field_plan=build_active_fit_field_plan(layout, set()),
    )
    assert data["extra_indicators"]["fit_K1_text"][0] is None


def test_precompute_keeps_imu_source_strict_and_preserves_real_zero():
    layout = {"indicators": {"accel_x_text": {"enabled": True, "source": "gpmf"}}}
    resolver = lambda field, source, target, key=None: (
        0.0 if field == "accel_x" and source == "gpmf" else None
    )
    cache = build_telemetry_cache(
        layout=layout, base_dt=BASE.replace(tzinfo=None), tz_offset_hours=0,
        start_dt_utc=BASE.replace(tzinfo=None), speed_samples=[],
        track_samples=[], alt_samples=[], total_frames=1,
        resolve_cache_value=resolver,
    )
    assert cache.lookup(0)["extra_indicators"]["accel_x_text"][0] == 0.0

    layout["indicators"]["accel_x_text"]["source"] = "fit"
    missing = build_telemetry_cache(
        layout=layout, base_dt=BASE.replace(tzinfo=None), tz_offset_hours=0,
        start_dt_utc=BASE.replace(tzinfo=None), speed_samples=[],
        track_samples=[], alt_samples=[], total_frames=1,
        resolve_cache_value=resolver,
    )
    assert missing.lookup(0)["extra_indicators"]["accel_x_text"][0] is None
