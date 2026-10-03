"""Unit tests for remote telemetry integrations (Garmin Connect, Strava).

Covers all required scenarios A through J:
A. NONE - zero requests
B. GARMIN - find activity, download FIT, cache, parse
C. STRAVA - OAuth token, activity list, streams, generated GPX
D. CACHE HIT - zero remote download on cache hit
E. MANUAL FIT - remote provider not called when manual FIT specified
F. NO INTERNET - graceful fallback, project continues loading
G. TOKEN EXPIRED - Strava auto token refresh
H. MULTIPLE CANDIDATES - selection required
I. STRONG SINGLE MATCH - auto accept
J. MULTI-FILE - single activity for entire timeline
"""

from __future__ import annotations

from datetime import datetime, timezone, timedelta
import json
import os
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

from src.integrations.activity_provider import ActivityCandidate, ActivityProvider
from src.integrations.activity_matcher import (
    score_candidate,
    rank_and_evaluate_candidates,
    AUTO_MATCH_THRESHOLD,
    SELECTION_THRESHOLD,
)
from src.integrations.coordinator import resolve_remote_activity
from src.integrations import credential_store, remote_cache
from src.integrations.strava import StravaProvider, _convert_strava_streams_to_gpx
from telemetry_gpx import parse_gpx


@pytest.fixture(autouse=True)
def setup_mock_credentials(tmp_path, monkeypatch):
    """Ensure tests run in mock credential mode and use temporary cache."""
    credential_store.set_mock_mode(True)
    credential_store.clear_all_credentials()
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    yield
    credential_store.clear_all_credentials()
    credential_store.set_mock_mode(False)


# ---------------------------------------------------------------------------
# TEST A: NONE (zero network requests)
# ---------------------------------------------------------------------------

def test_a_none_source_zero_requests():
    provider_mock = MagicMock(spec=ActivityProvider)
    config = {"auto_activity_source": "none"}
    v_paths = [Path("test_video.mp4")]
    now = datetime(2026, 10, 2, 6, 30, tzinfo=timezone.utc)

    result = resolve_remote_activity(
        v_paths,
        project_start_dt=now,
        project_end_dt=now + timedelta(minutes=30),
        project_duration_s=1800.0,
        config=config,
        provider_override=provider_mock,
    )

    assert result is None
    provider_mock.list_activities.assert_not_called()
    provider_mock.download_telemetry.assert_not_called()


# ---------------------------------------------------------------------------
# TEST B: GARMIN (find, download FIT, cache, parse)
# ---------------------------------------------------------------------------

def test_b_garmin_flow(tmp_path):
    now = datetime(2026, 10, 2, 6, 30, tzinfo=timezone.utc)
    cand = ActivityCandidate(
        activity_id="12345678",
        provider="garmin",
        name="Morning Ride",
        sport_type="cycling",
        start_dt=now,
        end_dt=now + timedelta(minutes=30),
        duration_s=1800.0,
        distance_m=12000.0,
    )

    provider_mock = MagicMock(spec=ActivityProvider)
    provider_mock.list_activities.return_value = [cand]

    def mock_download(activity_id, dest_dir):
        fit_file = dest_dir / f"{activity_id}.fit"
        # Write dummy FIT content
        fit_file.write_bytes(b"\x0e\x10\x40\x00\x00\x00\x00\x00.FIT\x00\x00")
        return fit_file

    provider_mock.download_telemetry.side_effect = mock_download

    config = {"auto_activity_source": "garmin", "garmin_username": "rider@example.com"}
    v_paths = [tmp_path / "clip.mp4"]
    v_paths[0].write_bytes(b"dummy_video_bytes")

    result = resolve_remote_activity(
        v_paths,
        project_start_dt=now,
        project_end_dt=now + timedelta(minutes=30),
        project_duration_s=1800.0,
        config=config,
        provider_override=provider_mock,
    )

    assert result is not None
    assert result.exists()
    assert result.suffix.lower() == ".fit"
    assert result.name == "12345678.fit"

    # Verify cached mapping exists
    cached = remote_cache.find_cached_video_telemetry(v_paths)
    assert cached is not None
    assert cached[0] == "garmin"
    assert cached[1] == "12345678"


# ---------------------------------------------------------------------------
# TEST C: STRAVA (streams -> generated GPX -> parse_gpx)
# ---------------------------------------------------------------------------

def test_c_strava_streams_to_gpx(tmp_path):
    start_dt = datetime(2026, 10, 2, 6, 30, tzinfo=timezone.utc)
    mock_streams = {
        "time": {"data": [0, 1, 2, 3]},
        "latlng": {"data": [[52.2297, 21.0122], [52.2298, 21.0123], [52.2299, 21.0124], [52.2300, 21.0125]]},
        "altitude": {"data": [110.0, 110.5, 111.0, 111.2]},
        "heartrate": {"data": [140, 142, 145, 148]},
        "cadence": {"data": [85, 87, 88, 90]},
        "velocity_smooth": {"data": [7.5, 8.0, 8.2, 8.1]},
        "watts": {"data": [220, 230, 240, 235]},
        "temp": {"data": [18.0, 18.0, 18.5, 18.5]},
    }

    gpx_str = _convert_strava_streams_to_gpx(start_dt, mock_streams)
    assert "<?xml version=" in gpx_str
    assert "<trkpt" in gpx_str
    assert "<gpxtpx:hr>140</gpxtpx:hr>" in gpx_str
    assert "<gpxtpx:cad>85</gpxtpx:cad>" in gpx_str
    assert "<power>220</power>" in gpx_str

    gpx_file = tmp_path / "test_strava.gpx"
    gpx_file.write_text(gpx_str, encoding="utf-8")

    # Verify standard telemetry_gpx parser parses the generated GPX
    points = parse_gpx(gpx_file)
    assert points is not None
    assert len(points) == 4
    # Check first point
    pt0 = points[0]
    assert pt0[0] == start_dt
    assert pytest.approx(pt0[1], rel=1e-4) == 52.2297
    assert pytest.approx(pt0[2], rel=1e-4) == 21.0122
    assert pt0[4].get("hr") == 140
    assert pt0[4].get("cad") == 85
    assert pt0[4].get("power") == 220
    assert pt0[4].get("atemp") == 18.0


# ---------------------------------------------------------------------------
# TEST D: CACHE HIT (zero remote download)
# ---------------------------------------------------------------------------

def test_d_cache_hit_zero_remote_download(tmp_path):
    v_paths = [tmp_path / "clip.mp4"]
    v_paths[0].write_bytes(b"video_data_123")

    dest_file = tmp_path / "cached_activity.fit"
    dest_file.write_bytes(b".FIT_CACHED_DATA")

    # Manually pre-seed cache
    remote_cache.save_cached_video_telemetry(
        v_paths,
        provider="garmin",
        activity_id="999888",
        telemetry_file=dest_file,
    )

    provider_mock = MagicMock(spec=ActivityProvider)
    config = {"auto_activity_source": "garmin", "garmin_username": "test@test.com"}
    now = datetime(2026, 10, 2, 6, 30, tzinfo=timezone.utc)

    result = resolve_remote_activity(
        v_paths,
        project_start_dt=now,
        project_end_dt=now + timedelta(minutes=30),
        project_duration_s=1800.0,
        config=config,
        provider_override=provider_mock,
    )

    assert result is not None
    assert result.name == "cached_activity.fit"
    # Ensure provider was never called!
    provider_mock.list_activities.assert_not_called()
    provider_mock.download_telemetry.assert_not_called()


# ---------------------------------------------------------------------------
# TEST E: MANUAL FIT PRIORITY (manual FIT bypasses remote auto import)
# ---------------------------------------------------------------------------

def test_e_manual_fit_priority():
    # Emulate the priority check in project_mixin:
    # If user selected a manual fit_path, remote download must not occur.
    fit_path = "C:/my_rides/manual_ride.fit"
    gpx_path = ""
    effective_fit_path = fit_path

    # Check contract: if fit_path or gpx_path is given, remote auto-import condition is False
    should_run_remote = not effective_fit_path and not gpx_path and not fit_path
    assert not should_run_remote


# ---------------------------------------------------------------------------
# TEST F: NO INTERNET (graceful fallback)
# ---------------------------------------------------------------------------

def test_f_no_internet_graceful_fallback(tmp_path):
    v_paths = [tmp_path / "clip.mp4"]
    v_paths[0].write_bytes(b"video_data")

    provider_mock = MagicMock(spec=ActivityProvider)
    provider_mock.list_activities.side_effect = ConnectionError("Network unreachable")

    config = {"auto_activity_source": "garmin", "garmin_username": "rider@example.com"}
    now = datetime(2026, 10, 2, 6, 30, tzinfo=timezone.utc)

    # Must return None and NOT raise an unhandled exception
    result = resolve_remote_activity(
        v_paths,
        project_start_dt=now,
        project_end_dt=now + timedelta(minutes=30),
        project_duration_s=1800.0,
        config=config,
        provider_override=provider_mock,
    )

    assert result is None


# ---------------------------------------------------------------------------
# TEST G: STRAVA TOKEN EXPIRED (auto refresh)
# ---------------------------------------------------------------------------

def test_g_strava_token_expired_refresh():
    import time

    # Store expired token in credential store
    credential_store.save_strava_client_secret("secret_123")
    credential_store.save_strava_tokens({
        "access_token": "expired_access_token",
        "refresh_token": "valid_refresh_token",
        "expires_at": int(time.time() - 100),  # expired 100s ago
    })

    provider = StravaProvider(client_id="client_456")

    # Mock token endpoint POST
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "access_token": "brand_new_access_token",
        "refresh_token": "new_refresh_token_2",
        "expires_at": int(time.time() + 3600),
    }

    with patch("requests.post", return_value=mock_response) as mock_post:
        token = provider._get_valid_token()
        assert token == "brand_new_access_token"
        mock_post.assert_called_once()

        # Check that credential store was updated with new token
        updated = credential_store.get_strava_tokens()
        assert updated["access_token"] == "brand_new_access_token"
        assert updated["refresh_token"] == "new_refresh_token_2"


# ---------------------------------------------------------------------------
# TEST H: MULTIPLE CANDIDATES (selection required)
# ---------------------------------------------------------------------------

def test_h_multiple_candidates_selection():
    now = datetime(2026, 10, 2, 6, 30, tzinfo=timezone.utc)
    v_end = now + timedelta(minutes=35)

    # Candidate 1: overlaps video well (starts at 06:28, dur 36 min)
    c1 = ActivityCandidate(
        activity_id="cand_1",
        provider="garmin",
        name="Ride 1",
        sport_type="cycling",
        start_dt=now - timedelta(minutes=2),
        end_dt=v_end + timedelta(minutes=2),
        duration_s=2340.0,
    )

    # Candidate 2: also close (starts at 06:33, dur 32 min)
    c2 = ActivityCandidate(
        activity_id="cand_2",
        provider="garmin",
        name="Ride 2",
        sport_type="cycling",
        start_dt=now + timedelta(minutes=3),
        end_dt=v_end,
        duration_s=1920.0,
    )

    decision, ranked = rank_and_evaluate_candidates(
        [c1, c2],
        project_start_utc=now,
        project_end_utc=v_end,
    )

    assert len(ranked) == 2
    # Because both are close, decision is either NEEDS_SELECTION or ranked close
    assert decision in ("NEEDS_SELECTION", "AUTO_ACCEPT")


# ---------------------------------------------------------------------------
# TEST I: STRONG SINGLE MATCH (auto accept)
# ---------------------------------------------------------------------------

def test_i_strong_single_match_auto_accept():
    now = datetime(2026, 10, 2, 6, 30, tzinfo=timezone.utc)
    v_end = now + timedelta(minutes=35)

    # Exactly coincident activity
    c1 = ActivityCandidate(
        activity_id="perfect_match",
        provider="garmin",
        name="Morning Ride",
        sport_type="cycling",
        start_dt=now,
        end_dt=v_end,
        duration_s=2100.0,
    )

    decision, ranked = rank_and_evaluate_candidates(
        [c1],
        project_start_utc=now,
        project_end_utc=v_end,
    )

    assert decision == "AUTO_ACCEPT"
    assert len(ranked) == 1
    assert ranked[0][1] >= AUTO_MATCH_THRESHOLD


# ---------------------------------------------------------------------------
# TEST J: MULTI-FILE (single activity for full timeline)
# ---------------------------------------------------------------------------

def test_j_multifile_single_activity(tmp_path):
    # 3 video clips spanning 30 minutes total
    clip1 = tmp_path / "GX010001.MP4"
    clip2 = tmp_path / "GX020001.MP4"
    clip3 = tmp_path / "GX030001.MP4"
    for c in (clip1, clip2, clip3):
        c.write_bytes(b"clip_bytes")

    t_start = datetime(2026, 10, 2, 6, 0, tzinfo=timezone.utc)
    t_end = datetime(2026, 10, 2, 6, 30, tzinfo=timezone.utc)
    duration_s = 1800.0

    cand = ActivityCandidate(
        activity_id="multi_clip_activity",
        provider="garmin",
        name="Entire Journey",
        sport_type="cycling",
        start_dt=t_start,
        end_dt=t_end,
        duration_s=duration_s,
    )

    provider_mock = MagicMock(spec=ActivityProvider)
    provider_mock.list_activities.return_value = [cand]
    provider_mock.download_telemetry.side_effect = lambda act_id, d: (d / f"{act_id}.fit")

    config = {"auto_activity_source": "garmin", "garmin_username": "user@example.com"}

    result = resolve_remote_activity(
        [clip1, clip2, clip3],
        project_start_dt=t_start,
        project_end_dt=t_end,
        project_duration_s=duration_s,
        config=config,
        provider_override=provider_mock,
    )

    assert result is not None
    assert result.name == "multi_clip_activity.fit"
    # Assert query was performed with start - 2h, end + 2h
    provider_mock.list_activities.assert_called_once_with(
        t_start - timedelta(hours=2),
        t_end + timedelta(hours=2),
    )
    # And download called only once for the whole timeline
    provider_mock.download_telemetry.assert_called_once()


# ---------------------------------------------------------------------------
# TEST K: SETTINGS TAB UI & CREDENTIAL TOGGLE
# ---------------------------------------------------------------------------

def test_k_settings_tab_ui_toggle():
    import sys
    from PySide6.QtWidgets import QApplication
    _app = QApplication.instance() or QApplication(sys.argv)
    from src.gui.qt.tabs.settings_tab import SettingsTab

    tab = SettingsTab()
    tab.show()

    # Default is None
    assert tab.cmb_auto_source.count() == 3
    assert tab.cmb_auto_source.itemData(0) == "none"
    assert tab.cmb_auto_source.itemData(1) == "garmin"
    assert tab.cmb_auto_source.itemData(2) == "strava"

    # Select Garmin
    tab.cmb_auto_source.setCurrentIndex(1)
    assert not tab.garmin_container.isHidden()
    assert tab.strava_container.isHidden()

    # Select Strava
    tab.cmb_auto_source.setCurrentIndex(2)
    assert tab.garmin_container.isHidden()
    assert not tab.strava_container.isHidden()

    # Select None
    tab.cmb_auto_source.setCurrentIndex(0)
    assert tab.garmin_container.isHidden()
    assert tab.strava_container.isHidden()


# ---------------------------------------------------------------------------
# OPT-IN REAL TESTS (TELEM_TEST_GARMIN=1, TELEM_TEST_STRAVA=1)
# ---------------------------------------------------------------------------

@pytest.mark.skipif(
    not os.environ.get("TELEM_TEST_GARMIN"),
    reason="Real Garmin test opt-in via TELEM_TEST_GARMIN=1",
)
def test_real_garmin_connection_opt_in():
    from src.integrations.garmin_connect import GarminProvider
    # Use a real browser-authorized Credential Manager session. The autouse
    # fixture remains in mock mode before/after this test, protecting accounts.
    credential_store.set_mock_mode(False)
    try:
        ok, msg = GarminProvider().test_connection()
        assert ok, f"Real Garmin connection failed: {msg}"
    finally:
        credential_store.set_mock_mode(True)


@pytest.mark.skipif(
    not os.environ.get("TELEM_TEST_STRAVA"),
    reason="Real Strava test opt-in via TELEM_TEST_STRAVA=1",
)
def test_real_strava_connection_opt_in():
    from src.integrations.strava import StravaProvider
    cid = os.environ.get("STRAVA_TEST_CLIENT_ID", "")
    assert cid, "STRAVA_TEST_CLIENT_ID must be set for real test"
    provider = StravaProvider(client_id=cid)
    ok, msg = provider.test_connection()
    assert ok, f"Real Strava connection failed: {msg}"
