from __future__ import annotations

import json
import os
from types import SimpleNamespace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

from src.integrations.activity_provider import ActivityCandidate, ActivityProvider
from src.integrations.auto_telemetry_preflight import (
    run_auto_telemetry_preflight,
    scan_and_match_local_telemetry,
)
from src.multifile import (
    TIMESTAMP_QUALITY_ESTIMATED,
    TIMESTAMP_QUALITY_FALLBACK,
    TIMESTAMP_SOURCE_FILE_MTIME,
    ClipTimestampResolution,
    _resolve_container_timestamp,
    resolve_clip_timestamp,
)


BASE = datetime(2026, 10, 5, 12, 0, tzinfo=timezone.utc)


def test_mp4_offset_timestamp_is_resolved_without_gps(tmp_path, monkeypatch):
    video = tmp_path / "DJI.MP4"
    video.write_bytes(b"synthetic")
    os.utime(video, (BASE.timestamp(), BASE.timestamp()))
    monkeypatch.setattr(
        "src.multifile._resolve_from_gpmf",
        lambda *a, **k: ClipTimestampResolution(
            timestamp_source="no_gps_time", timestamp_quality="fallback",
        ),
    )
    monkeypatch.setattr(
        "src.multifile.subprocess.run",
        lambda *a, **k: MagicMock(returncode=0, stdout=json.dumps({"format": {"tags": {
            "creation_time": "2026-10-05T14:00:00+02:00",
        }}, "streams": []})),
    )

    result = resolve_clip_timestamp(video, use_cache=False, duration_s=60)
    assert result.absolute_start_dt == datetime(2026, 10, 5, 12, 0)
    assert result.timestamp_quality == TIMESTAMP_QUALITY_ESTIMATED
    assert result.timestamp_reliable is True


def test_naive_or_invalid_container_dates_never_become_exact(tmp_path, monkeypatch):
    video = tmp_path / "camera.MP4"
    video.write_bytes(b"synthetic")
    monkeypatch.setattr(
        "src.multifile.subprocess.run",
        lambda *a, **k: MagicMock(returncode=0, stdout=json.dumps({"format": {"tags": {
            "creation_time": "2026-10-05T14:00:00",
        }}, "streams": []})),
    )
    result = _resolve_container_timestamp(video)
    assert result.timestamp_quality == TIMESTAMP_QUALITY_FALLBACK
    assert not result.timestamp_reliable
    assert "local time" in result.timestamp_detail

    monkeypatch.setattr(
        "src.multifile.subprocess.run",
        lambda *a, **k: MagicMock(returncode=0, stdout=json.dumps({"format": {"tags": {
            "creation_time": "2099-01-01T00:00:00Z",
        }}, "streams": []})),
    )
    result = _resolve_container_timestamp(video)
    assert result.absolute_start_dt is None


def test_filesystem_mtime_is_low_confidence_fallback(tmp_path):
    from src.multifile import _resolve_filesystem_mtime

    clip = tmp_path / "no_metadata.mp4"
    clip.write_bytes(b"synthetic")
    result = _resolve_filesystem_mtime(clip)
    assert result.timestamp_source == TIMESTAMP_SOURCE_FILE_MTIME
    assert result.timestamp_quality == TIMESTAMP_QUALITY_FALLBACK
    assert result.timestamp_reliable is False


def test_local_fit_auto_match_without_video_gps(tmp_path, monkeypatch):
    video = tmp_path / "clip.MP4"
    video.write_bytes(b"video")
    fit = tmp_path / "ride.fit"
    fit.write_bytes(b"fit")
    monkeypatch.setattr(
        "src.integrations.auto_telemetry_preflight.probe_fit_time_range",
        lambda _path: (BASE, BASE + timedelta(seconds=600), 600.0),
    )
    matched, diag = scan_and_match_local_telemetry(
        [video], [(BASE, BASE + timedelta(seconds=600), 600.0, "estimated")], tmp_path,
    )
    assert matched == fit
    assert diag["status"] == "matched"


def test_low_confidence_local_match_requires_existing_selection_callback(tmp_path, monkeypatch):
    video = tmp_path / "clip.MP4"
    video.write_bytes(b"video")
    fit = tmp_path / "ride.fit"
    fit.write_bytes(b"fit")
    monkeypatch.setattr(
        "src.integrations.auto_telemetry_preflight.probe_fit_time_range",
        lambda _path: (BASE, BASE + timedelta(seconds=600), 600.0),
    )
    interval = (BASE, BASE + timedelta(seconds=600), 600.0, "degraded")
    matched, diag = scan_and_match_local_telemetry([video], [interval], tmp_path)
    assert matched is None
    assert diag["status"] == "needs_selection"

    chosen = MagicMock()
    chosen.raw_data = {"path": str(fit.resolve())}
    matched, diag = scan_and_match_local_telemetry(
        [video], [interval], tmp_path, on_needs_selection=lambda _ranked: chosen,
    )
    assert matched == fit.resolve()
    assert diag["status"] == "selected"


def test_trustworthy_video_gps_fallback_ranks_fit_coordinates(tmp_path, monkeypatch):
    video = tmp_path / "clip.MP4"
    video.write_bytes(b"video")
    fit = tmp_path / "ride.fit"
    fit.write_bytes(b"fit")
    monkeypatch.setattr(
        "src.integrations.auto_telemetry_preflight.probe_fit_time_range",
        lambda _path: (BASE - timedelta(days=3), BASE - timedelta(days=3) + timedelta(seconds=600), 600.0),
    )
    fit_records = SimpleNamespace(gps_track=[
        (BASE, 52.0, 21.0), (BASE + timedelta(seconds=600), 52.001, 21.001),
    ])
    monkeypatch.setattr("telemetry_fit.parse_fit", lambda _path: fit_records)
    monkeypatch.setattr("telemetry_fit._haversine", lambda *_args: 10.0)
    matched, diag = scan_and_match_local_telemetry(
        [video], [(BASE, BASE + timedelta(seconds=600), 600.0, "exact")],
        tmp_path, video_gps_point=(52.0, 21.0),
    )
    assert matched == fit
    assert diag["status"] == "matched"


def test_candidates_from_multiple_local_directories_are_ambiguous(tmp_path, monkeypatch):
    video_dir = tmp_path / "video"
    configured_dir = tmp_path / "configured"
    video_dir.mkdir()
    configured_dir.mkdir()
    video = video_dir / "clip.mp4"
    video.write_bytes(b"video")
    (video_dir / "first.fit").write_bytes(b"fit")
    (configured_dir / "second.fit").write_bytes(b"fit")
    monkeypatch.setattr("psutil.disk_partitions", lambda **_kwargs: [])
    monkeypatch.setattr(
        "src.multifile.probe_clip_time_interval",
        lambda _path: (BASE, BASE + timedelta(seconds=600), 600.0, "exact"),
    )
    monkeypatch.setattr(
        "src.integrations.auto_telemetry_preflight.probe_fit_time_range",
        lambda _path: (BASE, BASE + timedelta(seconds=600), 600.0),
    )
    statuses = []
    result = run_auto_telemetry_preflight(
        [video], {"telemetry_dir": str(configured_dir), "auto_activity_source": "none"},
        lambda *status: statuses.append(status),
    )
    assert result is None
    assert any("Wymaga wyboru" in str(status) for status in statuses)


def test_unassociated_downloaded_fit_cache_is_searched(tmp_path, monkeypatch):
    video_dir = tmp_path / "video"
    garmin_cache = tmp_path / "cache" / "garmin"
    strava_cache = tmp_path / "cache" / "strava"
    video_dir.mkdir()
    garmin_cache.mkdir(parents=True)
    strava_cache.mkdir(parents=True)
    video = video_dir / "clip.mp4"
    video.write_bytes(b"video")
    cached_fit = garmin_cache / "activity.fit"
    cached_fit.write_bytes(b"fit")
    monkeypatch.setattr("psutil.disk_partitions", lambda **_kwargs: [])
    monkeypatch.setattr(
        "src.multifile.probe_clip_time_interval",
        lambda _path: (BASE, BASE + timedelta(seconds=600), 600.0, "exact"),
    )
    monkeypatch.setattr(
        "src.integrations.auto_telemetry_preflight.probe_fit_time_range",
        lambda _path: (BASE, BASE + timedelta(seconds=600), 600.0),
    )
    monkeypatch.setattr(
        "src.integrations.auto_telemetry_preflight.remote_cache.get_provider_cache_dir",
        lambda provider: garmin_cache if provider == "garmin" else strava_cache,
    )
    result = run_auto_telemetry_preflight(
        [video], {"auto_activity_source": "none"}, lambda *_status: None,
    )
    assert result == cached_fit


def test_strava_ambiguous_candidates_are_not_downloaded_without_selection(tmp_path, monkeypatch):
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"video")
    candidates = [
        ActivityCandidate(
            activity_id=str(i), provider="strava", name=f"ride {i}", sport_type="Ride",
            start_dt=BASE, end_dt=BASE + timedelta(seconds=600), duration_s=600,
        ) for i in (1, 2)
    ]
    provider = MagicMock(spec=ActivityProvider)
    provider.connect.return_value = True
    provider.list_activities.return_value = candidates
    monkeypatch.setattr("psutil.disk_partitions", lambda **_kwargs: [])
    monkeypatch.setattr(
        "src.multifile.probe_clip_time_interval",
        lambda _path: (BASE, BASE + timedelta(seconds=600), 600.0, "exact"),
    )
    monkeypatch.setattr(
        "src.integrations.auto_telemetry_preflight.remote_cache.find_cached_video_telemetry",
        lambda _paths: None,
    )
    statuses = []
    result = run_auto_telemetry_preflight(
        [video], {"auto_activity_source": "strava", "strava_client_id": "test"},
        lambda *status: statuses.append(status), provider_override=provider,
    )
    assert result is None
    provider.download_telemetry.assert_not_called()
    assert any("Wymaga wyboru" in str(status) for status in statuses)
