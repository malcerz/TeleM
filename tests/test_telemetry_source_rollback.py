from datetime import datetime
from pathlib import Path

from src.gui import telemetry_manager as telemetry_module
from src.gui.telemetry_manager import TelemetryDataManager


def test_fit_success_commits_requested_source(monkeypatch, tmp_path):
    source = tmp_path / "new.fit"
    source.write_bytes(b"fit")
    when = datetime(2026, 1, 1)
    manager = TelemetryDataManager()
    manager.start_dt_utc = when
    manager.fit_path = Path("old.fit")
    monkeypatch.setattr(telemetry_module, "parse_fit", lambda _path: [{"timestamp": when, "lat": None, "lon": None}])
    monkeypatch.setattr(telemetry_module, "sync_fit_to_video", lambda *_args: {"speed": [(when, 2.0)]})

    assert manager.load_fit("video.mp4", start_dt=when, manual_path=source)
    assert manager.fit_path == source
    assert manager.fit_data["speed"]


def test_fit_failure_preserves_previous_source_and_data(monkeypatch, tmp_path):
    source = tmp_path / "broken.fit"
    source.write_bytes(b"fit")
    when = datetime(2026, 1, 1)
    manager = TelemetryDataManager()
    manager.fit_path = Path("old.fit")
    manager.fit_data = {"heart_rate": [(when, 120.0)]}
    old_data = manager.fit_data
    monkeypatch.setattr(telemetry_module, "parse_fit", lambda _path: [{"timestamp": when, "lat": None, "lon": None}])
    monkeypatch.setattr(telemetry_module, "sync_fit_to_video", lambda *_args: {})

    assert manager.load_fit("video.mp4", start_dt=when, manual_path=source) is False
    assert manager.fit_path == Path("old.fit")
    assert manager.fit_data is old_data


def test_gpx_success_commits_requested_source(monkeypatch, tmp_path):
    source = tmp_path / "new.gpx"
    source.write_bytes(b"gpx")
    when = datetime(2026, 1, 1)
    points = [(when, 54.0, 18.0, 10.0, {})]
    manager = TelemetryDataManager()
    manager.start_dt_utc = when
    manager.gpx_path = Path("old.gpx")
    monkeypatch.setattr(telemetry_module, "parse_gpx", lambda _path: points)
    monkeypatch.setattr(telemetry_module, "sync_gpx_to_video", lambda *_args: ([], [], [], [], [], [], []))

    assert manager.load_gpx("video.mp4", start_dt=when, manual_path=source)
    assert manager.gpx_path == source


def test_gpx_failure_preserves_previous_source_and_data(monkeypatch, tmp_path):
    source = tmp_path / "bad.gpx"
    source.write_bytes(b"gpx")
    when = datetime(2026, 1, 1)
    old_gps = [(when, 53.0, 17.0)]
    manager = TelemetryDataManager()
    manager.gpx_path = Path("old.gpx")
    manager.gpx_gps_track = old_gps
    monkeypatch.setattr(telemetry_module, "parse_gpx", lambda _path: [(when, 54.0, 18.0, 10.0, {})])
    monkeypatch.setattr(telemetry_module, "sync_gpx_to_video", lambda *_args: None)

    assert manager.load_gpx("video.mp4", start_dt=when, manual_path=source) is False
    assert manager.gpx_path == Path("old.gpx")
    assert manager.gpx_gps_track is old_gps
