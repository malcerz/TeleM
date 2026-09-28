"""Acceptance tests for safe FIT/GPX validation and transactional loading."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

from src.telemetry_file_validation import (
    ValidationState,
    validate_telemetry_range,
)


BASE = datetime(2026, 9, 23, 8, 0, tzinfo=timezone.utc)


def _validate(kind: str, start: datetime, end: datetime, **kwargs):
    return validate_telemetry_range(
        file_type=kind,
        file_path=Path(f"candidate.{kind.lower()}"),
        video_start=BASE,
        video_end=BASE + timedelta(hours=1),
        telemetry_start=start,
        telemetry_end=end,
        point_count=10,
        **kwargs,
    )


def test_fit_same_activity_valid():
    result = _validate("FIT", BASE + timedelta(minutes=2), BASE + timedelta(minutes=58))
    assert result.state is ValidationState.VALID
    assert result.reason_code == "TIME_OVERLAP"


def test_fit_same_day_wrong_hour_rejected():
    result = _validate(
        "FIT", BASE + timedelta(hours=6), BASE + timedelta(hours=7)
    )
    assert result.state is ValidationState.INVALID
    assert result.reason_code == "DATE_TIME_MISMATCH"


def test_fit_wrong_date_rejected():
    result = _validate(
        "FIT", BASE - timedelta(days=1), BASE - timedelta(days=1) + timedelta(hours=1)
    )
    assert result.state is ValidationState.INVALID
    assert result.reason_code == "DATE_TIME_MISMATCH"


def test_fit_overlap_with_different_start_valid():
    result = _validate("FIT", BASE - timedelta(minutes=2), BASE + timedelta(minutes=20))
    assert result.state is ValidationState.VALID
    assert result.overlap_seconds > 0


def test_gpx_same_activity_valid():
    result = _validate("GPX", BASE + timedelta(minutes=1), BASE + timedelta(minutes=59))
    assert result.state is ValidationState.VALID


def test_gpx_wrong_date_rejected():
    result = _validate(
        "GPX", BASE + timedelta(days=2), BASE + timedelta(days=2, hours=1)
    )
    assert result.state is ValidationState.INVALID
    assert result.reason_code == "DATE_TIME_MISMATCH"


def test_gpx_wrong_hour_rejected():
    result = _validate(
        "GPX", BASE + timedelta(hours=6), BASE + timedelta(hours=7)
    )
    assert result.state is ValidationState.INVALID
    assert result.reason_code == "DATE_TIME_MISMATCH"


def test_gpx_without_time_unknown():
    result = validate_telemetry_range(
        file_type="GPX",
        file_path=Path("untimed.gpx"),
        video_start=BASE,
        video_end=BASE + timedelta(hours=1),
        telemetry_start=None,
        telemetry_end=None,
        point_count=25,
    )
    assert result.state is ValidationState.UNKNOWN
    assert result.reason_code == "NO_TIMESTAMPS"
    assert result.can_force_load


def test_corrupt_gpx_error():
    result = _validate("GPX", BASE, BASE, parse_error="invalid XML")
    assert result.state is ValidationState.INVALID
    assert result.reason_code == "CORRUPT_FILE"
    assert "uszkodzony" in result.message


def test_corrupt_fit_error():
    result = _validate("FIT", BASE, BASE, parse_error="invalid FIT")
    assert result.state is ValidationState.INVALID
    assert result.reason_code == "CORRUPT_FILE"


def _project_validation_dummy(tmp_path, accepted: bool):
    from src.gui.qt._mixins.project_mixin import ProjectMixin

    path = tmp_path / "candidate.fit"
    path.write_bytes(b"placeholder")
    dummy = SimpleNamespace(
        video_timeline=None,
        video_paths=[],
        video_duration_s=3600.0,
        telemetry=SimpleNamespace(start_dt_utc=BASE),
        _project_video_time_range=lambda: (BASE, BASE + timedelta(hours=1)),
        _request_telemetry_validation=lambda _result: accepted,
    )
    records = [
        {"timestamp": BASE + timedelta(minutes=2), "lat": 1.0, "lon": 2.0},
        {"timestamp": BASE + timedelta(minutes=3), "lat": 1.1, "lon": 2.1},
    ]
    ok, parsed = ProjectMixin._validate_external_telemetry_candidate(
        dummy, "FIT", path, records
    )
    return dummy, path, ok, parsed


def test_cancel_keeps_previous_fit(tmp_path):
    dummy, old_path, ok, _ = _project_validation_dummy(tmp_path, accepted=False)
    dummy.fit_path = old_path
    assert not ok
    assert dummy.fit_path == old_path


def test_cancel_keeps_previous_gpx(tmp_path):
    from src.gui.qt._mixins.project_mixin import ProjectMixin

    path = tmp_path / "candidate.gpx"
    path.write_text("<gpx/>", encoding="utf-8")
    old_path = tmp_path / "current.gpx"
    dummy = SimpleNamespace(
        video_timeline=None,
        video_paths=[],
        video_duration_s=3600.0,
        telemetry=SimpleNamespace(start_dt_utc=BASE),
        _project_video_time_range=lambda: (BASE, BASE + timedelta(hours=1)),
        _request_telemetry_validation=lambda _result: False,
        gpx_path=old_path,
    )
    ok, _ = ProjectMixin._validate_external_telemetry_candidate(dummy, "GPX", path)
    assert not ok
    assert dummy.gpx_path == old_path


def test_override_accepts_mismatch(tmp_path):
    _dummy, _path, ok, parsed = _project_validation_dummy(tmp_path, accepted=True)
    assert ok
    assert parsed


def test_rejected_file_does_not_start_smartsync(tmp_path, monkeypatch):
    from src.gui.qt._mixins.project_mixin import ProjectMixin

    called = []
    monkeypatch.setattr(
        "src.gui.telemetry_manager._compute_smart_time_offset",
        lambda *args, **kwargs: called.append(True),
    )
    dummy, _path, ok, _ = _project_validation_dummy(tmp_path, accepted=False)
    assert not ok
    assert called == []


def test_multiclip_video_range_validation():
    result = validate_telemetry_range(
        file_type="FIT",
        file_path=Path("multiclip.fit"),
        video_start=BASE,
        video_end=BASE + timedelta(minutes=30),
        telemetry_start=BASE - timedelta(minutes=2),
        telemetry_end=BASE + timedelta(minutes=35),
        point_count=20,
    )
    assert result.state is ValidationState.VALID
    assert result.overlap_seconds == 1800.0


def test_validation_uses_candidate_video_not_previous_video(tmp_path, monkeypatch):
    from src.gui.qt._mixins.project_mixin import ProjectMixin

    video_a = tmp_path / "video_a.mp4"
    video_b = tmp_path / "video_b.mp4"
    video_b.write_bytes(b"candidate")
    fit_path = tmp_path / "candidate.fit"
    fit_path.write_bytes(b"candidate fit")
    old_clip = SimpleNamespace(
        absolute_start_dt=BASE - timedelta(days=1),
        absolute_end_dt=BASE - timedelta(days=1) + timedelta(hours=1),
    )
    candidate_range = (BASE, BASE + timedelta(hours=1))

    def fake_probe(path, **_kwargs):
        assert Path(path) == video_b
        return candidate_range[0], candidate_range[1], 3600.0, "exact"

    monkeypatch.setattr("src.multifile.probe_clip_time_interval", fake_probe)
    seen = []
    dummy = SimpleNamespace(
        video_timeline=SimpleNamespace(clips=[old_clip]),
        video_paths=[video_a],
        telemetry=SimpleNamespace(start_dt_utc=BASE - timedelta(days=1)),
        _request_telemetry_validation=lambda result: seen.append(result) or True,
    )
    actual_range = ProjectMixin._project_video_time_range(dummy, [video_b])
    records = [
        {"timestamp": BASE + timedelta(minutes=5), "lat": 1.0, "lon": 2.0},
        {"timestamp": BASE + timedelta(minutes=10), "lat": 1.1, "lon": 2.1},
    ]
    ok, _ = ProjectMixin._validate_external_telemetry_candidate(
        dummy, "FIT", fit_path, records,
        video_time_range=actual_range,
    )
    assert actual_range == candidate_range
    assert ok
    assert seen[0].state is ValidationState.VALID
    assert seen[0].video_start == BASE


def test_validation_only_fit_change_uses_current_video():
    from src.gui.qt._mixins.project_mixin import ProjectMixin

    current_start = BASE + timedelta(days=1)
    dummy = SimpleNamespace(
        video_timeline=SimpleNamespace(clips=[SimpleNamespace(
            absolute_start_dt=current_start,
            absolute_end_dt=current_start + timedelta(hours=1),
        )]),
        video_paths=[Path("current.mp4")],
    )
    assert ProjectMixin._project_video_time_range(dummy) == (
        current_start,
        current_start + timedelta(hours=1),
    )

