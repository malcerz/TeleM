"""Test suite for automatic telemetry preflight immediately on MP4 selection.

Covers all requirements from prompt:
1. test_auto_search_starts_on_mp4_selection
2. test_local_fit_found_without_load_click
3. test_local_gpx_found_without_load_click
4. test_local_file_priority_over_remote
5. test_none_source_zero_remote_requests
6. test_garmin_starts_after_local_miss
7. test_strava_starts_after_local_miss
8. test_stale_result_is_ignored
9. test_clear_cancels_auto_search
10. test_manual_file_priority
11. test_multifile_one_search
12. test_remote_cache_before_network
13. test_load_does_not_duplicate_search
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
import time
from unittest.mock import MagicMock, patch
import pytest

os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PySide6.QtWidgets import QApplication

from src.gui.qt.tabs.load_tab import LoadTab
from src.integrations.activity_provider import ActivityCandidate, ActivityProvider
from src.integrations import credential_store, remote_cache
from src.integrations.auto_telemetry_preflight import (
    probe_gpx_time_range,
    scan_and_match_local_telemetry,
    run_auto_telemetry_preflight,
)


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture(autouse=True)
def setup_tmp_cache(tmp_path, monkeypatch):
    credential_store.set_mock_mode(True)
    credential_store.clear_all_credentials()
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setattr(LoadTab, "_start_info_inspection", lambda self, *a, **k: None)
    monkeypatch.setattr(LoadTab, "_start_multi_info_inspection", lambda self, *a, **k: None)
    yield
    credential_store.clear_all_credentials()
    credential_store.set_mock_mode(False)


def _wait_for_condition(cond_fn, timeout=3.0, step=0.01):
    app = QApplication.instance()
    deadline = time.time() + timeout
    while time.time() < deadline:
        if app:
            app.processEvents()
        if cond_fn():
            return True
        time.sleep(step)
    if app:
        app.processEvents()
    return cond_fn()


# ---------------------------------------------------------------------------
# 1. test_auto_search_starts_on_mp4_selection
# ---------------------------------------------------------------------------
def test_auto_search_starts_on_mp4_selection(qapp, tmp_path):
    tab = LoadTab()
    mp4_file = tmp_path / "trip.mp4"
    mp4_file.write_bytes(b"dummy")

    with patch.object(tab, "_start_auto_telemetry_preflight") as mock_start:
        tab.set_video_paths([str(mp4_file)], start_search=True)
        assert mock_start.called
        assert tab._video_paths == [str(mp4_file.resolve())]
    tab.close()


# ---------------------------------------------------------------------------
# 2. test_local_fit_found_without_load_click
# ---------------------------------------------------------------------------
def test_local_fit_found_without_load_click(qapp, tmp_path):
    tab = LoadTab()
    video = tmp_path / "GX010338.MP4"
    video.write_bytes(b"video_bytes")
    fit = tmp_path / "GX010338.fit"
    fit.write_bytes(b"fit_bytes")

    now = datetime(2026, 10, 2, 6, 30, tzinfo=timezone.utc)
    intervals = [(now, now + timedelta(minutes=30), 1800.0, "exact")]

    with patch("src.multifile.probe_clip_time_interval", return_value=(now, now + timedelta(minutes=30), 1800.0, "exact")), \
         patch("src.integrations.auto_telemetry_preflight.probe_fit_time_range", return_value=(now, now + timedelta(minutes=30), 1800.0)), \
         patch("src.integrations.coordinator.resolve_remote_activity") as mock_remote:

        tab.set_video_paths([str(video)], start_search=True)
        assert _wait_for_condition(lambda: bool(tab._fit_path))

        assert tab._fit_path == str(fit.resolve())
        assert fit.name in tab.btn_telemetry.text()
        assert tab.btn_telemetry.text().endswith("✓")
        assert tab.btn_telemetry.toolTip() == str(fit.resolve())
        mock_remote.assert_not_called()
    tab.close()


# ---------------------------------------------------------------------------
# 3. test_local_gpx_found_without_load_click
# ---------------------------------------------------------------------------
def test_local_gpx_found_without_load_click(qapp, tmp_path):
    tab = LoadTab()
    video = tmp_path / "ride.mp4"
    video.write_bytes(b"video")
    gpx = tmp_path / "ride.gpx"
    gpx.write_bytes(b"<gpx></gpx>")

    now = datetime(2026, 10, 2, 8, 0, tzinfo=timezone.utc)

    with patch("src.multifile.probe_clip_time_interval", return_value=(now, now + timedelta(minutes=45), 2700.0, "exact")), \
         patch("src.integrations.auto_telemetry_preflight.probe_gpx_time_range", return_value=(now, now + timedelta(minutes=45), 2700.0)), \
         patch("src.integrations.coordinator.resolve_remote_activity") as mock_remote:

        tab.set_video_paths([str(video)], start_search=True)
        assert _wait_for_condition(lambda: bool(tab._gpx_path))

        assert tab._gpx_path == str(gpx.resolve())
        assert gpx.name in tab.btn_telemetry.text()
        assert tab.btn_telemetry.text().endswith("✓")
        mock_remote.assert_not_called()
    tab.close()


# ---------------------------------------------------------------------------
# 4. test_local_file_priority_over_remote
# ---------------------------------------------------------------------------
def test_local_file_priority_over_remote(qapp, tmp_path):
    tab = LoadTab()
    video = tmp_path / "vid.mp4"
    video.write_bytes(b"video")
    local_fit = tmp_path / "vid.fit"
    local_fit.write_bytes(b"local_fit")

    remote_fit = tmp_path / "remote_cached.fit"
    remote_fit.write_bytes(b"remote_fit")

    # Seed remote cache
    remote_cache.save_cached_video_telemetry([video], "garmin", "999", remote_fit)

    now = datetime(2026, 10, 2, 8, 0, tzinfo=timezone.utc)

    with patch("src.multifile.probe_clip_time_interval", return_value=(now, now + timedelta(minutes=30), 1800.0, "exact")), \
         patch("src.integrations.auto_telemetry_preflight.probe_fit_time_range", return_value=(now, now + timedelta(minutes=30), 1800.0)), \
         patch("src.integrations.coordinator.resolve_remote_activity") as mock_remote:

        tab.set_video_paths([str(video)], start_search=True)
        assert _wait_for_condition(lambda: bool(tab._fit_path))

        # Local FIT must win over remote cache!
        assert tab._fit_path == str(local_fit.resolve())
        assert local_fit.name in tab.btn_telemetry.text()
        mock_remote.assert_not_called()
    tab.close()


# ---------------------------------------------------------------------------
# 5. test_none_source_zero_remote_requests
# ---------------------------------------------------------------------------
def test_none_source_zero_remote_requests(qapp, tmp_path):
    tab = LoadTab()
    video = tmp_path / "vid_no_telem.mp4"
    video.write_bytes(b"video")

    now = datetime(2026, 10, 2, 8, 0, tzinfo=timezone.utc)

    with patch.object(tab, "_get_integrations_config", return_value={"auto_activity_source": "none"}), \
         patch("src.multifile.probe_clip_time_interval", return_value=(now, now + timedelta(minutes=20), 1200.0, "exact")), \
         patch("src.integrations.coordinator.resolve_remote_activity") as mock_remote:

        tab.set_video_paths([str(video)], start_search=True)
        assert _wait_for_condition(lambda: "Nie znaleziono lokalnego FIT/GPX" in tab.btn_telemetry.text())

        assert tab._fit_path == ""
        assert tab._gpx_path == ""
        assert "Nie znaleziono lokalnego FIT/GPX" in tab.btn_telemetry.text()
        mock_remote.assert_not_called()
    tab.close()


# ---------------------------------------------------------------------------
# 6. test_garmin_starts_after_local_miss
# ---------------------------------------------------------------------------
def test_garmin_starts_after_local_miss(qapp, tmp_path):
    tab = LoadTab()
    video = tmp_path / "no_local_garmin.mp4"
    video.write_bytes(b"video")

    now = datetime(2026, 10, 2, 8, 0, tzinfo=timezone.utc)

    cand = ActivityCandidate(
        activity_id="555666",
        provider="garmin",
        name="Morning Garmin Ride",
        sport_type="cycling",
        start_dt=now,
        end_dt=now + timedelta(minutes=30),
        duration_s=1800.0,
        distance_m=12000.0,
    )

    provider_mock = MagicMock(spec=ActivityProvider)
    provider_mock.connect.return_value = True
    provider_mock.list_activities.return_value = [cand]

    downloaded_fit = tmp_path / "555666.fit"
    downloaded_fit.write_bytes(b".FIT_DATA")
    provider_mock.download_telemetry.return_value = downloaded_fit

    with patch.object(tab, "_get_integrations_config", return_value={"auto_activity_source": "garmin"}), \
         patch("src.integrations.auto_telemetry_preflight.GarminProvider", return_value=provider_mock), \
         patch("src.multifile.probe_clip_time_interval", return_value=(now, now + timedelta(minutes=30), 1800.0, "exact")):

        tab.set_video_paths([str(video)], start_search=True)
        assert _wait_for_condition(lambda: bool(tab._fit_path))

        assert tab._fit_path == str(downloaded_fit.resolve())
        assert "555666.fit" in tab.btn_telemetry.text()
        assert tab.btn_telemetry.text().endswith("✓")
    tab.close()


# ---------------------------------------------------------------------------
# 7. test_strava_starts_after_local_miss
# ---------------------------------------------------------------------------
def test_strava_starts_after_local_miss(qapp, tmp_path):
    tab = LoadTab()
    video = tmp_path / "no_local_strava.mp4"
    video.write_bytes(b"video")

    now = datetime(2026, 10, 2, 8, 0, tzinfo=timezone.utc)

    cand = ActivityCandidate(
        activity_id="777888",
        provider="strava",
        name="Morning Strava Ride",
        sport_type="cycling",
        start_dt=now,
        end_dt=now + timedelta(minutes=30),
        duration_s=1800.0,
        distance_m=12000.0,
    )

    provider_mock = MagicMock(spec=ActivityProvider)
    provider_mock.connect.return_value = True
    provider_mock.list_activities.return_value = [cand]

    downloaded_gpx = tmp_path / "777888.gpx"
    downloaded_gpx.write_bytes(b"<gpx></gpx>")
    provider_mock.download_telemetry.return_value = downloaded_gpx

    with patch.object(tab, "_get_integrations_config", return_value={"auto_activity_source": "strava", "strava_client_id": "123"}), \
         patch("src.integrations.auto_telemetry_preflight.StravaProvider", return_value=provider_mock), \
         patch("src.multifile.probe_clip_time_interval", return_value=(now, now + timedelta(minutes=30), 1800.0, "exact")):

        tab.set_video_paths([str(video)], start_search=True)
        assert _wait_for_condition(lambda: bool(tab._gpx_path))

        assert tab._gpx_path == str(downloaded_gpx.resolve())
        assert tab.btn_telemetry.text().endswith("✓")
    tab.close()


# ---------------------------------------------------------------------------
# 8. test_stale_result_is_ignored
# ---------------------------------------------------------------------------
def test_stale_result_is_ignored(qapp, tmp_path):
    tab = LoadTab()
    vid_a = tmp_path / "video_a.mp4"
    vid_a.write_bytes(b"a")
    vid_b = tmp_path / "video_b.mp4"
    vid_b.write_bytes(b"b")

    now = datetime(2026, 10, 2, 8, 0, tzinfo=timezone.utc)
    fit_a = tmp_path / "fit_a.fit"
    fit_a.write_bytes(b"fit_a")

    # Start search for A with gen 1
    tab._video_paths = [str(vid_a)]
    tab._autofit_gen = 1

    # Before A finishes, user selects B (gen 2)
    tab._video_paths = [str(vid_b)]
    tab._autofit_gen = 2

    # Emit stale match for gen 1
    tab._on_autofit_matched(str(fit_a), gen=1)
    tab._on_autofit_status("fit_a.fit ✓", "Gotowe", gen=1, tooltip=str(fit_a))

    # Gen 1 must be ignored!
    assert tab._fit_path == ""
    assert "fit_a.fit" not in tab.btn_telemetry.text()
    tab.close()


# ---------------------------------------------------------------------------
# 9. test_clear_cancels_auto_search
# ---------------------------------------------------------------------------
def test_clear_cancels_auto_search(qapp, tmp_path):
    import threading
    tab = LoadTab()
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"test")

    tab.set_video_paths([str(video)], start_search=False)
    tab._autofit_in_progress = True
    cancel_ev = threading.Event()
    tab._autofit_cancel_event = cancel_ev
    gen_before = tab._autofit_gen

    tab._on_clear()

    assert cancel_ev.is_set()
    assert tab._autofit_cancel_event is None
    assert tab._autofit_gen > gen_before
    assert tab._autofit_in_progress is False
    assert tab._video_paths == []
    assert tab._fit_path == ""
    assert tab._gpx_path == ""
    assert tab.btn_telemetry.text() == "Wybierz FIT/GPX (opcjonalnie)..."
    tab.close()


# ---------------------------------------------------------------------------
# 10. test_manual_file_priority
# ---------------------------------------------------------------------------
def test_manual_file_priority(qapp, tmp_path):
    tab = LoadTab()
    manual_fit = tmp_path / "manual_user_chosen.fit"
    manual_fit.write_bytes(b"manual")

    tab._user_selected_telemetry = True
    tab._manual_fit_path = str(manual_fit)
    tab._fit_path = str(manual_fit)
    tab.btn_telemetry.setText(manual_fit.name)

    # An auto preflight returns a different file
    auto_fit = tmp_path / "auto_found.fit"
    auto_fit.write_bytes(b"auto")

    tab._on_autofit_matched(str(auto_fit), gen=tab._autofit_gen)
    tab._on_autofit_status("auto_found.fit ✓", "Gotowe", gen=tab._autofit_gen, tooltip=str(auto_fit))

    # Manual selection must never be replaced by auto search!
    assert tab._fit_path == str(manual_fit)
    assert tab.btn_telemetry.text() == manual_fit.name
    tab.close()


# ---------------------------------------------------------------------------
# 11. test_multifile_one_search
# ---------------------------------------------------------------------------
def test_multifile_one_search(qapp, tmp_path):
    video1 = tmp_path / "clip1.mp4"
    video2 = tmp_path / "clip2.mp4"
    video1.write_bytes(b"1")
    video2.write_bytes(b"2")

    now = datetime(2026, 10, 2, 8, 0, tzinfo=timezone.utc)
    c1 = (now, now + timedelta(minutes=15), 900.0, "exact")
    c2 = (now + timedelta(minutes=15), now + timedelta(minutes=30), 900.0, "exact")

    cand = ActivityCandidate(
        activity_id="multi123",
        provider="garmin",
        name="Combined Ride",
        sport_type="cycling",
        start_dt=now,
        end_dt=now + timedelta(minutes=30),
        duration_s=1800.0,
        distance_m=10000.0,
    )

    provider_mock = MagicMock(spec=ActivityProvider)
    provider_mock.connect.return_value = True
    provider_mock.list_activities.return_value = [cand]

    downloaded = tmp_path / "multi123.fit"
    downloaded.write_bytes(b".FIT")
    provider_mock.download_telemetry.return_value = downloaded

    with patch("src.multifile.probe_clip_time_interval", side_effect=[c1, c2]):
        result = run_auto_telemetry_preflight(
            video_paths=[video1, video2],
            config={"auto_activity_source": "garmin"},
            on_status=lambda *args: None,
            provider_override=provider_mock,
        )

        assert result == downloaded
        # Exactly one query for the entire multi-file project timeline
        assert provider_mock.list_activities.call_count == 1


# ---------------------------------------------------------------------------
# 12. test_remote_cache_before_network
# ---------------------------------------------------------------------------
def test_remote_cache_before_network(qapp, tmp_path):
    video = tmp_path / "cached_clip.mp4"
    video.write_bytes(b"video")
    cached_file = tmp_path / "cached_act.fit"
    cached_file.write_bytes(b"cached_fit")

    remote_cache.save_cached_video_telemetry([video], "garmin", "888999", cached_file)

    provider_mock = MagicMock(spec=ActivityProvider)
    now = datetime(2026, 10, 2, 8, 0, tzinfo=timezone.utc)

    with patch("src.multifile.probe_clip_time_interval", return_value=(now, now + timedelta(minutes=30), 1800.0, "exact")):
        result = run_auto_telemetry_preflight(
            video_paths=[video],
            config={"auto_activity_source": "garmin"},
            on_status=lambda *args: None,
            provider_override=provider_mock,
        )

        assert result == cached_file
        # ZERO remote network calls on cache hit!
        provider_mock.list_activities.assert_not_called()
        provider_mock.download_telemetry.assert_not_called()


# ---------------------------------------------------------------------------
# 13. test_load_does_not_duplicate_search
# ---------------------------------------------------------------------------
def test_load_does_not_duplicate_search(qapp, tmp_path):
    tab = LoadTab()
    video = tmp_path / "load_test.mp4"
    video.write_bytes(b"video")

    tab._video_paths = [str(video)]
    tab._fit_path = "C:/already/found.fit"
    tab._autofit_in_progress = False

    signals_mock = MagicMock()
    tab.signals = signals_mock

    tab._on_load()

    # sig_files_selected is emitted with already-found FIT
    signals_mock.sig_files_selected.emit.assert_called_once_with(
        [str(video)], "", "C:/already/found.fit"
    )
    tab.close()
