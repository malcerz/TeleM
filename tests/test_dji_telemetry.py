"""DJI adapter tests; real Action 6 parsing is an opt-in separate check."""

from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
import os

import pytest

from src import telemetry_dji
from src.gui.telemetry_manager import TelemetryDataManager


def test_detect_by_djmd_metadata_not_filename(monkeypatch, tmp_path):
    def fake_run(*args, **kwargs):
        return SimpleNamespace(stdout=json.dumps({"streams": [
            {"codec_type": "data", "codec_tag_string": "djmd", "tags": {"handler_name": "CAM meta"}},
        ]}))

    monkeypatch.setattr(telemetry_dji.subprocess, "run", fake_run)
    assert telemetry_dji.detect_camera_telemetry(tmp_path / "ordinary.mp4", "ffprobe") == "dji_djmd"


def test_gopro_gpmf_has_priority_and_unchanged_path(monkeypatch, tmp_path):
    monkeypatch.setattr(telemetry_dji.subprocess, "run", lambda *a, **k: SimpleNamespace(stdout=json.dumps({
        "streams": [{"codec_type": "data", "codec_tag_string": "gpmd"}],
    })))
    assert telemetry_dji.detect_camera_telemetry(tmp_path / "DJI_looks_like.mp4", "ffprobe") == "gopro_gpmf"


def test_adapter_maps_imu_units_timestamps_and_caches_without_gps(monkeypatch, tmp_path):
    source = tmp_path / "clip.mp4"
    source.write_bytes(b"camera")
    monkeypatch.setattr(telemetry_dji, "get_media_cache_dir", lambda _source: tmp_path / "central_cache")
    calls = []

    class Parser:
        camera = "DJI"
        model = "OsmoAction6"

        def __init__(self, path):
            calls.append(path)

        def telemetry(self):
            return [{"Default": {"Metadata": {"clip_meta_header": {"product_name": "DJI OsmoAction6"}}}},
                    {"Quaternion": {"Data": [{"t": 0.5, "v": {"w": 1, "x": 0, "y": 0, "z": 0}}]}}]

        def normalized_imu(self):
            return [{"timestamp_ms": 500.25, "gyro": [180.0, 0.0, -90.0], "accl": [0.0, 9.80665, 0.0]}]

    monkeypatch.setattr(telemetry_dji, "_parser_module", lambda: SimpleNamespace(Parser=Parser))
    anchor = datetime(2026, 9, 28, 5, 16, 57, tzinfo=timezone.utc)
    cold = telemetry_dji.load_dji_telemetry(source, anchor)
    warm = telemetry_dji.load_dji_telemetry(source, anchor)
    assert len(calls) == 1
    assert cold["cache_hit"] is False and warm["cache_hit"] is True
    assert cold["gyroscope_samples"][0][0] == anchor.replace(microsecond=500250)
    assert cold["gyroscope_samples"][0][1] == pytest.approx((math.pi, 0, -math.pi / 2))
    assert cold["accelerometer_samples"][0][1] == pytest.approx((0, 9.80665, 0))
    assert len(cold["quaternion_samples"]) == 1
    assert "gps_track" not in cold and "speed_samples" not in cold
    assert not list(tmp_path.glob("*.json"))


def test_manager_keeps_fit_gps_and_exposes_existing_imu_indicators():
    manager = TelemetryDataManager()
    instant = datetime(2026, 9, 28, tzinfo=timezone.utc)
    manager.fit_data = {"speed_samples": [(instant, 5.0)]}
    manager.fit_gps_track = [(instant, 51.0, 17.0)]
    manager.load_dji_telemetry({
        "gyroscope_samples": [(instant, (1.0, 2.0, 3.0))],
        "accelerometer_samples": [(instant, (4.0, 5.0, 6.0))],
        "quaternion_samples": [(instant, (1.0, 0.0, 0.0, 0.0))],
    })
    assert len(manager.gyro_x_samples) == 1
    assert len(manager.accel_magnitude_samples) == 1
    assert manager.fit_data["speed_samples"][0][1] == 5.0
    assert manager.fit_gps_track[0][1:] == (51.0, 17.0)
    assert manager.gps_track == []


def test_two_clips_keep_absolute_monotonic_imu_time(monkeypatch, tmp_path):
    monkeypatch.setattr(telemetry_dji, "get_media_cache_dir", lambda path: tmp_path / (Path(path).stem + "_cache"))

    class Parser:
        camera = "DJI"
        model = "OsmoAction6"

        def __init__(self, path):
            pass

        def telemetry(self):
            return []

        def normalized_imu(self):
            return [{"timestamp_ms": 0.0, "gyro": [1, 2, 3], "accl": [4, 5, 6]},
                    {"timestamp_ms": 999.5, "gyro": [1, 2, 3], "accl": [4, 5, 6]}]

    monkeypatch.setattr(telemetry_dji, "_parser_module", lambda: SimpleNamespace(Parser=Parser))
    first = tmp_path / "first.mp4"
    second = tmp_path / "second.mp4"
    first.write_bytes(b"first")
    second.write_bytes(b"second")
    anchor = datetime(2026, 9, 28, tzinfo=timezone.utc)
    a = telemetry_dji.load_dji_telemetry(first, anchor)
    b = telemetry_dji.load_dji_telemetry(second, anchor.replace(second=2))
    stamps = [item[0] for data in (a, b) for item in data["gyroscope_samples"]]
    assert stamps == sorted(stamps)
    assert stamps[2] > stamps[1]
    assert len(a["accelerometer_samples"]) == len(b["accelerometer_samples"]) == 2


def test_missing_runtime_reports_python_abi(monkeypatch, tmp_path):
    monkeypatch.setattr(telemetry_dji, "DJI_RUNTIME", tmp_path / "missing")
    with pytest.raises(RuntimeError, match="Python 3.14"):
        telemetry_dji._parser_module()


@pytest.mark.skipif(not os.environ.get("TELEM_DJI_REAL_FILE"), reason="real DJI file opt-in")
def test_real_action6_project_loader_uses_dji_path_without_gps():
    from src.gui.qt._mixins.project_mixin import ProjectMixin

    source = Path(os.environ["TELEM_DJI_REAL_FILE"])
    harness = SimpleNamespace(ffprobe_exe=os.environ.get("TELEM_FFPROBE_EXE", r"C:\tools\ffprobe.exe"))
    fields, records = ProjectMixin._load_single_clip_telemetry(harness, source)
    assert records == []
    assert fields["_dji"] is True
    assert fields["camera"] == "DJI"
    assert fields["model"] == "OsmoAction6"
    assert "gps_track" not in fields
