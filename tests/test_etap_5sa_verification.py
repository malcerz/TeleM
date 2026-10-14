"""Unit tests for Stage 5S-A:
1. File collision detection using SHA-256 (same byte size, different content).
2. Timezone normalization in render_preparation (_vectorize_heading, _vectorize_lean_roll, etc.).
3. Multi-directory video source FIT/GPX search without scanning external folders.
"""

from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch
import zoneinfo
import numpy as np
import pytest

from src.integrations.activity_provider import ActivityCandidate
from src.integrations.auto_telemetry_preflight import (
    _compute_file_sha256,
    _files_content_identical,
    persist_downloaded_telemetry,
    run_auto_telemetry_preflight,
    resolve_local_fit,
)
from src.render_preparation import (
    _normalize_dt_to_utc,
    _vectorize_heading,
    _vectorize_lean_roll,
    _vectorize_linear_channel,
)


# ---------------------------------------------------------------------------
# 1. Collision tests: Two different FIT files with the EXACT SAME size
# ---------------------------------------------------------------------------
def test_fit_collision_same_size_different_content(tmp_path):
    video_dir = tmp_path / "videos"
    video_dir.mkdir()
    video = video_dir / "clip1.mp4"
    video.write_bytes(b"dummy_mp4")

    # Create two different FIT byte sequences of the exact same length (32 bytes)
    fit_content_a = b"GARMIN_FIT_STREAM_VERSION_0001_A"
    fit_content_b = b"GARMIN_FIT_STREAM_VERSION_0001_B"
    assert len(fit_content_a) == len(fit_content_b)
    assert fit_content_a != fit_content_b

    download_a = tmp_path / "download_a.fit"
    download_a.write_bytes(fit_content_a)

    download_b = tmp_path / "download_b.fit"
    download_b.write_bytes(fit_content_b)

    # Verify SHA-256 differences
    sha_a = _compute_file_sha256(download_a)
    sha_b = _compute_file_sha256(download_b)
    assert sha_a != sha_b
    assert not _files_content_identical(download_a, download_b)

    fixed_dt = datetime(2026, 10, 14, 10, 0, 0, tzinfo=timezone.utc)
    cand_a = ActivityCandidate(
        activity_id="act_1111",
        provider="garmin",
        name="Ride A",
        sport_type="cycling",
        start_dt=fixed_dt,
        end_dt=fixed_dt + timedelta(minutes=30),
        duration_s=1800.0,
        raw_data={"startTimeLocal": "2026-10-14 10:00:00"},
    )
    cand_b = ActivityCandidate(
        activity_id="act_2222",
        provider="garmin",
        name="Ride B",
        sport_type="cycling",
        start_dt=fixed_dt,
        end_dt=fixed_dt + timedelta(minutes=30),
        duration_s=1800.0,
        raw_data={"startTimeLocal": "2026-10-14 10:00:00"},
    )

    # Persist first file
    saved_a = persist_downloaded_telemetry(download_a, cand_a, [video])
    assert saved_a.exists()
    assert saved_a.name == "2026-10-14_10-00-00.fit"
    assert saved_a.read_bytes() == fit_content_a

    # Now persist second file with same target base name and identical byte size
    saved_b = persist_downloaded_telemetry(download_b, cand_b, [video])
    assert saved_b.exists()

    # The original file MUST NOT be overwritten!
    assert saved_a.read_bytes() == fit_content_a
    # The new file MUST be saved under a non-colliding name preserving its content
    assert saved_b != saved_a
    assert saved_b.read_bytes() == fit_content_b
    assert "act_2222" in saved_b.name

    # If file A is persisted again, it should return saved_a without duplicating
    saved_a_again = persist_downloaded_telemetry(download_a, cand_a, [video])
    assert saved_a_again == saved_a
    assert saved_a.read_bytes() == fit_content_a


# ---------------------------------------------------------------------------
# 2. Timezone tests in render_preparation
# ---------------------------------------------------------------------------
def test_timezone_normalization_cases():
    # Case A: UTC naive -> normalized to UTC aware with identical timestamp
    dt_naive = datetime(2026, 10, 14, 12, 0, 0)
    norm_naive = _normalize_dt_to_utc(dt_naive)
    assert norm_naive.tzinfo == timezone.utc
    assert norm_naive.year == 2026 and norm_naive.hour == 12

    # Case B: UTC aware -> remains identical UTC
    dt_aware_utc = datetime(2026, 10, 14, 12, 0, 0, tzinfo=timezone.utc)
    norm_aware_utc = _normalize_dt_to_utc(dt_aware_utc)
    assert norm_aware_utc == dt_aware_utc

    # Elapsed seconds between naive UTC and aware UTC must be exactly zero
    assert (norm_naive - norm_aware_utc).total_seconds() == 0.0

    # Case C: UTC aware + local timestamp with explicit offset (e.g. Warsaw CEST UTC+2)
    tz_cest = timezone(timedelta(hours=2))
    dt_local = datetime(2026, 10, 14, 14, 0, 0, tzinfo=tz_cest)
    norm_local = _normalize_dt_to_utc(dt_local)
    assert norm_local.hour == 12  # 14:00+02:00 == 12:00Z
    assert (norm_local - norm_aware_utc).total_seconds() == 0.0

    # Case D: DST boundary crossing (summer to winter transition with aware timestamps)
    from datetime import tzinfo

    class MockDSTTimezone(tzinfo):
        def utcoffset(self, dt):
            if dt is not None and getattr(dt, "fold", 0) == 0 and dt.hour == 2:
                return timedelta(hours=2)  # Summer time (+2) before switch
            return timedelta(hours=1)      # Winter time (+1) after switch

        def dst(self, dt):
            if dt is not None and getattr(dt, "fold", 0) == 0 and dt.hour == 2:
                return timedelta(hours=1)
            return timedelta(0)

        def tzname(self, dt):
            return "CEST" if getattr(dt, "fold", 0) == 0 and dt.hour == 2 else "CET"

    dst_tz = MockDSTTimezone()
    dt_before_dst = datetime(2026, 10, 25, 2, 30, fold=0, tzinfo=dst_tz)  # 00:30 UTC
    dt_after_dst = datetime(2026, 10, 25, 2, 30, fold=1, tzinfo=dst_tz)   # 01:30 UTC
    norm_before = _normalize_dt_to_utc(dt_before_dst)
    norm_after = _normalize_dt_to_utc(dt_after_dst)
    # The real time difference is 1 hour (3600s), continuous and accurate
    assert (norm_after - norm_before).total_seconds() == 3600.0


def test_vectorize_heading_and_lean_with_mixed_timezones():
    # Reference datetime: aware UTC at 10:00:00
    ref_dt = datetime(2026, 10, 14, 10, 0, 0, tzinfo=timezone.utc)
    target_ts = np.array([0.0, 10.0, 20.0], dtype=np.float64)

    # Samples with mixed aware timezones (UTC and UTC+2)
    tz_plus2 = timezone(timedelta(hours=2))
    heading_samples = [
        (datetime(2026, 10, 14, 10, 0, 0, tzinfo=timezone.utc), 90.0),       # ts = 0s
        (datetime(2026, 10, 14, 12, 0, 10, tzinfo=tz_plus2), 180.0),         # 12:00:10+2 == 10:00:10Z -> ts = 10s
        (datetime(2026, 10, 14, 10, 0, 20, tzinfo=timezone.utc), 270.0),     # ts = 20s
    ]

    h_res = _vectorize_heading(heading_samples, target_ts, ref_dt)
    assert np.isclose(h_res[0], 90.0)
    assert np.isclose(h_res[1], 180.0)
    assert np.isclose(h_res[2], 270.0)

    # Lean samples with naive ref_dt (representing GPS/FIT native time)
    ref_dt_naive = datetime(2026, 10, 14, 10, 0, 0)
    lean_samples = [
        (datetime(2026, 10, 14, 10, 0, 0), -5.0),
        (datetime(2026, 10, 14, 12, 0, 10, tzinfo=tz_plus2), 0.0),
        (datetime(2026, 10, 14, 10, 0, 20, tzinfo=timezone.utc), 12.0),
    ]

    lean_res = _vectorize_lean_roll(lean_samples, target_ts, ref_dt_naive)
    assert np.isclose(lean_res[0], -5.0)
    assert np.isclose(lean_res[1], 0.0)
    assert np.isclose(lean_res[2], 12.0)


# ---------------------------------------------------------------------------
# 3. Multi-file FIT/GPX search across different directories
# ---------------------------------------------------------------------------
def test_multi_dir_video_telemetry_search(tmp_path):
    dir_a = tmp_path / "camera_front"
    dir_b = tmp_path / "camera_rear"
    dir_a.mkdir()
    dir_b.mkdir()

    video_a = dir_a / "clip_a.mp4"
    video_b = dir_b / "clip_b.mp4"
    video_a.write_bytes(b"video_a")
    video_b.write_bytes(b"video_b")

    # FIT file is placed only in dir_b (second video folder)
    fit_in_b = dir_b / "activity_b.fit"
    fit_in_b.write_bytes(b"fit_in_b")

    now = datetime(2026, 10, 14, 8, 0, 0, tzinfo=timezone.utc)
    interval_a = (now, now + timedelta(minutes=10), 600.0, "exact")
    interval_b = (now + timedelta(minutes=10), now + timedelta(minutes=20), 600.0, "exact")

    def mock_probe_clip(p):
        if Path(p).name == "clip_a.mp4":
            return interval_a
        return interval_b

    with patch("src.multifile.probe_clip_time_interval", side_effect=mock_probe_clip), \
         patch("src.integrations.auto_telemetry_preflight.probe_fit_time_range", return_value=(now, now + timedelta(minutes=20), 1200.0)):

        # Calling run_auto_telemetry_preflight with videos from both folders
        matched = run_auto_telemetry_preflight(
            video_paths=[video_a, video_b],
            config={"auto_activity_source": "none"},
            on_status=lambda *args: None,
        )

        assert matched is not None, "Failed to locate FIT in second video directory!"
        assert matched.resolve() == fit_in_b.resolve()
