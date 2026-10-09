"""Tests for DJI Action 2 telemetry loading, manager lifecycle, and remote cache semantics.

Covers:
- test_dji_manager_exists_before_load
- test_dji_single_file_load_does_not_call_none
- test_dji_multifile_load_does_not_call_none
- test_dji_and_fit_can_coexist
- test_late_fit_attach_preserves_dji
- test_clear_then_reload_reinitializes_dji_correctly
- test_stale_dji_worker_result_is_ignored
- test_remote_fit_cache_is_not_independent_source
- test_local_auto_fit_only_exact_mp4_dir
"""

import threading
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

from src.gui.qt.controller import AppController
from src.gui.telemetry_manager import TelemetryDataManager
from src.integrations.auto_telemetry_preflight import (
    resolve_local_fit,
    run_auto_telemetry_preflight,
)


def test_dji_manager_exists_before_load():
    """Verify AppController initializes self.telemetry as a valid TelemetryDataManager."""
    ctrl = AppController()
    assert ctrl.telemetry is not None
    assert isinstance(ctrl.telemetry, TelemetryDataManager)
    assert ctrl.ensure_telemetry_manager() is ctrl.telemetry


def test_clear_then_reload_reinitializes_dji_correctly():
    """Verify that clear_project() preserves or re-instantiates self.telemetry instead of leaving it None."""
    ctrl = AppController()
    assert ctrl.telemetry is not None

    # Clear project
    ctrl.clear_project()
    assert ctrl.telemetry is not None
    assert isinstance(ctrl.telemetry, TelemetryDataManager)

    # Calling ensure_telemetry_manager returns the manager
    tm = ctrl.ensure_telemetry_manager()
    assert tm is not None
    assert tm is ctrl.telemetry


def test_dji_single_file_load_does_not_call_none(tmp_path):
    """Verify that loading a single DJI clip does not raise 'NoneType' has no attribute 'load_dji_telemetry'."""
    ctrl = AppController()
    ctrl.clear_project()  # simulate state after user clicked clear

    video_file = tmp_path / "DJI_0010.MP4"
    video_file.write_bytes(b"\x00" * 1024)

    dummy_fields = {
        "_dji": True,
        "start_dt_utc": datetime(2026, 10, 5, 12, 0, 0, tzinfo=timezone.utc),
        "gyroscope_samples": [],
        "accelerometer_samples": [],
        "quaternion_samples": [],
        "camera_metadata": {"proto": "dvtm_ac103.proto"},
    }

    with patch.object(ctrl, "_load_single_clip_telemetry", return_value=(dummy_fields, [])):
        ctrl.video_path = video_file
        ctrl.video_paths = [video_file]
        ctrl._load_or_generate_telemetry()

    assert ctrl.telemetry is not None
    assert ctrl.telemetry.is_dji is True
    assert ctrl.telemetry.camera_metadata == {"proto": "dvtm_ac103.proto"}


def test_dji_multifile_load_does_not_call_none(tmp_path):
    """Verify loading multi-clip DJI sequence does not fail on None and merges all clips."""
    ctrl = AppController()
    ctrl.clear_project()

    clips = [tmp_path / f"DJI_001{i}.MP4" for i in range(6)]
    for c in clips:
        c.write_bytes(b"\x00" * 1024)

    def mock_single_clip(path, clip_idx=0, total_clips=1):
        return {
            "_dji": True,
            "start_dt_utc": datetime(2026, 10, 5, 12, clip_idx, 0, tzinfo=timezone.utc),
            "gyroscope_samples": [
                (datetime(2026, 10, 5, 12, clip_idx, 0, tzinfo=timezone.utc), (0.1, 0.2, 0.3))
            ],
            "accelerometer_samples": [
                (datetime(2026, 10, 5, 12, clip_idx, 0, tzinfo=timezone.utc), (0.0, 0.0, 9.81))
            ],
            "quaternion_samples": [
                (datetime(2026, 10, 5, 12, clip_idx, 0, tzinfo=timezone.utc), (1.0, 0.0, 0.0, 0.0))
            ],
            "derived_angular_velocity_samples": [
                (datetime(2026, 10, 5, 12, clip_idx, 0, tzinfo=timezone.utc), (0.1, 0.2, 0.3))
            ],
            "white_balance_samples": [
                (datetime(2026, 10, 5, 12, clip_idx, 0, tzinfo=timezone.utc), 5500.0)
            ],
            "camera_metadata": {"proto": "dvtm_ac103.proto", "clip_idx": clip_idx},
            "has_derived_angular_velocity": True,
        }, []

    with patch.object(ctrl, "_load_single_clip_telemetry", side_effect=mock_single_clip):
        ctrl.video_path = clips[0]
        ctrl.video_paths = clips
        ctrl._load_or_generate_telemetry()

    assert ctrl.telemetry is not None
    assert ctrl.telemetry.is_dji is True
    # Verify all 6 clips were merged
    assert len(ctrl.telemetry.gyroscope_samples) == 6
    assert len(ctrl.telemetry.accelerometer_samples) == 6
    assert len(ctrl.telemetry.quaternion_samples) == 6
    assert len(ctrl.telemetry.derived_angular_velocity_samples) == 6
    assert len(ctrl.telemetry.white_balance_samples) == 6
    assert len(ctrl.telemetry.quaternion_w_samples) == 6


def test_dji_and_fit_can_coexist():
    """Verify DJI camera data and FIT activity data cleanly coexist on TelemetryDataManager."""
    tm = TelemetryDataManager()

    dji_data = {
        "gyroscope_samples": [(datetime(2026, 10, 5, 12, 0, 0), (0.1, 0.2, 0.3))],
        "accelerometer_samples": [(datetime(2026, 10, 5, 12, 0, 0), (0.0, 0.0, 9.81))],
        "quaternion_samples": [(datetime(2026, 10, 5, 12, 0, 0), (1.0, 0.0, 0.0, 0.0))],
        "derived_angular_velocity_samples": [(datetime(2026, 10, 5, 12, 0, 0), (0.1, 0.2, 0.3))],
        "camera_metadata": {"camera": "DJI Action 2"},
        "start_dt_utc": datetime(2026, 10, 5, 12, 0, 0),
    }

    tm.load_dji_telemetry(dji_data)
    assert tm.is_dji is True
    assert len(tm.gyroscope_samples) == 1

    # Now load mock FIT data without destroying DJI state
    raw_fit_records = [
        {"timestamp": datetime(2026, 10, 5, 12, 0, 0), "speed": 8.5, "heart_rate": 145, "lat": 50.0, "lon": 20.0},
        {"timestamp": datetime(2026, 10, 5, 12, 0, 1), "speed": 8.7, "heart_rate": 147, "lat": 50.0001, "lon": 20.0001},
    ]

    with patch("src.gui.telemetry_manager._FIT_AVAILABLE", True), \
         patch("src.gui.telemetry_manager.find_fit_for_video", return_value=None):
        tm._raw_fit_records = [dict(r) for r in raw_fit_records]
        tm.fit_path = Path("test.fit")
        tm._apply_fit_dataset(offset_s=0.0)

    # DJI streams remain intact
    assert tm.is_dji is True
    assert len(tm.gyroscope_samples) == 1
    assert len(tm.accelerometer_samples) == 1
    assert tm.camera_metadata == {"camera": "DJI Action 2"}

    # FIT data is available alongside DJI
    assert tm.fit_data is not None
    assert "heart_rate" in tm.available_fit_fields
    assert len(tm.fit_gps_track) == 2


def test_late_fit_attach_preserves_dji(tmp_path):
    """Verify that attach_late_telemetry preserves DJI state and sets FIT data."""
    ctrl = AppController()
    dummy_fields = {
        "_dji": True,
        "start_dt_utc": datetime(2026, 10, 5, 12, 0, 0, tzinfo=timezone.utc),
        "gyroscope_samples": [(datetime(2026, 10, 5, 12, 0, 0), (0.1, 0.2, 0.3))],
        "accelerometer_samples": [],
        "quaternion_samples": [],
        "camera_metadata": {"camera": "Action 2"},
    }

    video_file = tmp_path / "DJI_0010.MP4"
    video_file.write_bytes(b"\x00" * 1024)
    ctrl.video_path = video_file
    ctrl.video_paths = [video_file]

    with patch.object(ctrl, "_load_single_clip_telemetry", return_value=(dummy_fields, [])):
        ctrl._load_or_generate_telemetry()

    assert ctrl.telemetry.is_dji is True

    fit_file = tmp_path / "activity.fit"
    fit_file.write_bytes(b"\x00" * 100)

    with patch.object(ctrl.telemetry, "load_fit", return_value=True), \
         patch.object(ctrl.telemetry, "register_fit_fields", return_value=["speed", "heart_rate"]):
        res = ctrl.attach_late_telemetry(fit_file)

    assert res is True
    assert ctrl.telemetry.is_dji is True
    assert ctrl.fit_path == fit_file
    assert len(ctrl.telemetry.gyroscope_samples) == 1


def test_stale_dji_worker_result_is_ignored(tmp_path):
    """Verify that if _load_cancel_event is set, loading terminates and does not attach stale data."""
    ctrl = AppController()
    ctrl._load_cancel_event = threading.Event()
    ctrl._load_cancel_event.set()  # cancelled

    video_file = tmp_path / "DJI_0010.MP4"
    video_file.write_bytes(b"\x00" * 1024)
    ctrl.video_path = video_file
    ctrl.video_paths = [video_file]

    single_clip_called = False
    def mock_clip(*args, **kwargs):
        nonlocal single_clip_called
        single_clip_called = True
        return {"_dji": True}, []

    with patch.object(ctrl, "_load_single_clip_telemetry", side_effect=mock_clip):
        ctrl._load_or_generate_telemetry()

    assert single_clip_called is False
    assert ctrl.telemetry.is_dji is False


def test_remote_fit_cache_is_not_independent_source(tmp_path):
    """Verify that remote cache hit presents the provider (Garmin Connect or Strava), not generic 'Cache'."""
    video_paths = [tmp_path / "DJI_0010.MP4"]
    for p in video_paths:
        p.write_bytes(b"\x00" * 1024)

    cached_fit = tmp_path / "24614281884.fit"
    cached_fit.write_bytes(b"\x00" * 1024)

    statuses = []
    def on_status(field_st, row_st, path):
        statuses.append((field_st, row_st, path))

    config = {"auto_activity_source": "garmin"}

    with patch("src.integrations.auto_telemetry_preflight.resolve_local_fit", return_value=None), \
         patch("src.integrations.auto_telemetry_preflight.remote_cache.find_cached_video_telemetry",
               return_value=("garmin", "24614281884", cached_fit)):
        res = run_auto_telemetry_preflight(video_paths, config=config, on_status=on_status)

    assert res == cached_fit
    assert len(statuses) > 0
    field_st, row_st, path = statuses[-1]

    # Verify that the provider label is Garmin Connect, not 'Znaleziono w cache'
    assert "Znaleziono w cache" not in field_st
    assert "Znaleziono w cache" not in row_st
    assert "Garmin Connect" in row_st
    assert field_st.endswith("✓")


def test_local_auto_fit_only_exact_mp4_dir(tmp_path):
    """Verify resolve_local_fit scans strictly the exact directory of the source video."""
    video_dir = tmp_path / "videos"
    video_dir.mkdir()
    other_dir = tmp_path / "other"
    other_dir.mkdir()

    video_path = video_dir / "DJI_0010.MP4"
    video_path.write_bytes(b"\x00" * 1024)

    # FIT in a different directory should NEVER be matched
    unrelated_fit = other_dir / "activity.fit"
    unrelated_fit.write_bytes(b"\x00" * 1024)

    res = resolve_local_fit([video_path])
    assert res is None
