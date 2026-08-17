"""ETAP 1 contract tests: source selection, aliases, zero and map tracks."""

from datetime import datetime, timedelta

from src.gui.telemetry_manager import TelemetryDataManager
from src.indicators.chart_builder import build_chart_data
from src.telemetry_extract import interpolate_value
from src.ffmpeg.worker_cache import WORKER_CACHE, _resolve_cache_value


BASE = datetime(2026, 1, 1, 12, 0, 0)


def samples(value):
    return [(BASE, value), (BASE + timedelta(seconds=1), value)]


def manager_with_sources():
    manager = TelemetryDataManager(interpolate_fn=interpolate_value)
    manager.speed_samples = samples(10.0)
    manager.gpx_hr_samples = samples(100.0)
    manager.gpx_power_samples = samples(110.0)
    manager.gpx_cad_samples = samples(90.0)
    manager.gpx_battery_samples = samples(40.0)
    manager.fit_data = {
        "speed": samples(30.0),
        "heart_rate": samples(150.0),
        "curVpower": samples(210.0),
        "cadence": samples(120.0),
        "battery_soc": samples(80.0),
    }
    manager.gps_track = [(BASE, 1.0, 2.0), (BASE + timedelta(seconds=1), 1.1, 2.1)]
    manager.fit_gps_track = [(BASE, 9.0, 8.0), (BASE + timedelta(seconds=1), 9.1, 8.1)]
    return manager


def test_speed_source_is_authoritative():
    manager = manager_with_sources()
    assert manager.resolve_value("speed", BASE, source="gpmf") == 10.0
    assert manager.resolve_value("speed", BASE, source="fit") == 30.0


def test_sensor_aliases_follow_requested_source():
    manager = manager_with_sources()
    assert manager.resolve_value("hr", BASE, source="gpx") == 100.0
    assert manager.resolve_value("hr", BASE, source="fit") == 150.0
    assert manager.resolve_value("power", BASE, source="gpx") == 110.0
    assert manager.resolve_value("power", BASE, source="fit") == 210.0
    assert manager.resolve_value("cad", BASE, source="gpx") == 90.0
    assert manager.resolve_value("cad", BASE, source="fit") == 120.0
    assert manager.resolve_value("battery", BASE, source="gpx") == 40.0
    assert manager.resolve_value("battery", BASE, source="fit") == 80.0


def test_zero_is_not_missing():
    manager = TelemetryDataManager(interpolate_fn=interpolate_value)
    manager.fit_data["cadence"] = samples(0.0)
    assert manager.resolve_value("cad", BASE, source="fit") == 0.0
    assert manager.resolve_value("cad", BASE, source="gpmf") is None


def test_map_source_is_strict_and_has_no_fallback():
    manager = manager_with_sources()
    assert manager.get_gps_track_for_source("gpmf")[0][1:] == (1.0, 2.0)
    assert manager.get_gps_track_for_source("fit")[0][1:] == (9.0, 8.0)
    manager.fit_gps_track = []
    assert manager.get_gps_track_for_source("fit") == []


def test_chart_history_uses_indicator_source():
    manager = manager_with_sources()
    layout = {
        "indicators": {
            "power_text": {"form": "chart", "enabled": True, "source": "fit"},
            "hr_text": {"form": "chart", "enabled": True, "source": "gpx"},
        }
    }
    data = build_chart_data(
        layout,
        manager.get_samples_for_source,
        lambda field, source, key=None: manager.resolve_samples(field, source, key),
    )
    assert data["power_text"] == [210.0, 210.0]
    assert data["hr_text"] == [100.0, 100.0]


def test_worker_resolver_matches_manager_source_policy(monkeypatch):
    monkeypatch.setitem(WORKER_CACHE, "field_samples", {"speed_samples": samples(10.0)})
    monkeypatch.setitem(WORKER_CACHE, "fit_data", {"speed": samples(30.0)})
    assert _resolve_cache_value("speed", "gpmf", BASE) == 10.0
    assert _resolve_cache_value("speed", "fit", BASE) == 30.0
    assert _resolve_cache_value("speed", "gpx", BASE) is None
