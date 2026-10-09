"""Comprehensive test suite for telemetry source priority order and asynchronous resolution.

Hierarchy:
1. Manual FIT/GPX
2. Local matching .fit in exact MP4 directory (non-recursive, *.fit only)
3. Asynchronous remote integration (Garmin OR Strava, zero blocking, late attach)

Hard Invariants:
- Project loading NEVER waits for network (BLOCKING_REMOTE_WAIT=0).
- Local auto-search is strictly Path(video_path).parent / "*.fit".
- If local FIT matches: zero remote requests (REMOTE_REQUESTS=0).
- Zero cross-provider fallback (Garmin <-> Strava).
- Deduplication: at most 1 remote lookup per video selection.
- Stale result rejection on video switch or clear.
- Manual selection immediately cancels and overrides in-flight remote lookup.
"""

from datetime import datetime, timedelta, timezone
from pathlib import Path
import threading
import time
from unittest.mock import MagicMock, patch
import pytest

from src.integrations.activity_provider import ActivityCandidate, ActivityProvider
from src.integrations.auto_telemetry_preflight import (
    TelemetryOrchestrator,
    resolve_local_fit,
    resolve_telemetry_source_for_video,
    run_auto_telemetry_preflight,
    scan_and_match_local_telemetry,
)


@pytest.fixture(autouse=True)
def reset_orchestrator():
    """Ensure clean orchestrator state before each test."""
    orch = TelemetryOrchestrator.get_instance()
    orch.on_project_cleared()
    yield
    orch.on_project_cleared()


# ---------------------------------------------------------------------------
# 1. Local FIT in exact MP4 directory vs subfolders / parent / external
# ---------------------------------------------------------------------------
def test_local_fit_in_exact_mp4_dir_matches(tmp_path):
    mp4 = tmp_path / "clip.mp4"
    mp4.write_bytes(b"mp4")
    fit = tmp_path / "clip.fit"
    fit.write_bytes(b"fit")

    now = datetime(2026, 10, 2, 10, 0, tzinfo=timezone.utc)
    with patch("src.multifile.probe_clip_time_interval", return_value=(now, now + timedelta(minutes=30), 1800.0, "exact")), \
         patch("src.integrations.auto_telemetry_preflight.probe_fit_time_range", return_value=(now, now + timedelta(minutes=30), 1800.0)):
        matched = resolve_local_fit([mp4])
        assert matched is not None
        assert matched.resolve() == fit.resolve()


def test_fit_in_subfolder_not_matched(tmp_path):
    mp4 = tmp_path / "clip.mp4"
    mp4.write_bytes(b"mp4")
    sub = tmp_path / "subfolder"
    sub.mkdir()
    sub_fit = sub / "clip.fit"
    sub_fit.write_bytes(b"fit")

    now = datetime(2026, 10, 2, 10, 0, tzinfo=timezone.utc)
    with patch("src.multifile.probe_clip_time_interval", return_value=(now, now + timedelta(minutes=30), 1800.0, "exact")), \
         patch("src.integrations.auto_telemetry_preflight.probe_fit_time_range", return_value=(now, now + timedelta(minutes=30), 1800.0)):
        matched = resolve_local_fit([mp4])
        # Invariant: subfolders MUST NOT be scanned
        assert matched is None


def test_fit_in_parent_or_external_not_matched(tmp_path):
    video_dir = tmp_path / "video_dir"
    video_dir.mkdir()
    mp4 = video_dir / "clip.mp4"
    mp4.write_bytes(b"mp4")

    # Fit in parent directory
    parent_fit = tmp_path / "clip.fit"
    parent_fit.write_bytes(b"fit")

    # Fit in external directory
    ext_dir = tmp_path / "other"
    ext_dir.mkdir()
    ext_fit = ext_dir / "clip.fit"
    ext_fit.write_bytes(b"fit")

    now = datetime(2026, 10, 2, 10, 0, tzinfo=timezone.utc)
    with patch("src.multifile.probe_clip_time_interval", return_value=(now, now + timedelta(minutes=30), 1800.0, "exact")), \
         patch("src.integrations.auto_telemetry_preflight.probe_fit_time_range", return_value=(now, now + timedelta(minutes=30), 1800.0)):
        matched = resolve_local_fit([mp4])
        assert matched is None


def test_gpx_in_mp4_dir_not_matched_locally(tmp_path):
    mp4 = tmp_path / "clip.mp4"
    mp4.write_bytes(b"mp4")
    gpx = tmp_path / "clip.gpx"
    gpx.write_bytes(b"<gpx></gpx>")

    now = datetime(2026, 10, 2, 10, 0, tzinfo=timezone.utc)
    with patch("src.multifile.probe_clip_time_interval", return_value=(now, now + timedelta(minutes=30), 1800.0, "exact")), \
         patch("src.integrations.auto_telemetry_preflight.probe_gpx_time_range", return_value=(now, now + timedelta(minutes=30), 1800.0)):
        matched = resolve_local_fit([mp4])
        # Invariant: local auto-search is *.fit only, never matches .gpx automatically
        assert matched is None


# ---------------------------------------------------------------------------
# 2. Priority 1: Manual FIT / GPX wins over everything
# ---------------------------------------------------------------------------
def test_manual_fit_from_another_directory_wins(tmp_path):
    mp4 = tmp_path / "clip.mp4"
    mp4.write_bytes(b"mp4")
    local_fit = tmp_path / "clip.fit"
    local_fit.write_bytes(b"local_fit")

    manual_dir = tmp_path / "manual"
    manual_dir.mkdir()
    manual_fit = manual_dir / "user_chosen.fit"
    manual_fit.write_bytes(b"manual")

    resolved = resolve_telemetry_source_for_video(
        video_paths=[mp4],
        config={"auto_activity_source": "garmin"},
        manual_fit=str(manual_fit),
    )
    assert resolved == manual_fit


def test_manual_gpx_wins(tmp_path):
    mp4 = tmp_path / "clip.mp4"
    mp4.write_bytes(b"mp4")
    local_fit = tmp_path / "clip.fit"
    local_fit.write_bytes(b"local_fit")

    manual_gpx = tmp_path / "manual.gpx"
    manual_gpx.write_bytes(b"<gpx></gpx>")

    resolved = resolve_telemetry_source_for_video(
        video_paths=[mp4],
        config={"auto_activity_source": "garmin"},
        manual_gpx=str(manual_gpx),
    )
    assert resolved == manual_gpx


# ---------------------------------------------------------------------------
# 3. Priority 2: Local FIT match terminates search (ZERO remote calls)
# ---------------------------------------------------------------------------
def test_local_fit_terminates_search_zero_remote_calls(tmp_path):
    mp4 = tmp_path / "clip.mp4"
    mp4.write_bytes(b"mp4")
    fit = tmp_path / "clip.fit"
    fit.write_bytes(b"fit")

    remote_mock = MagicMock(spec=ActivityProvider)
    now = datetime(2026, 10, 2, 10, 0, tzinfo=timezone.utc)

    with patch("src.multifile.probe_clip_time_interval", return_value=(now, now + timedelta(minutes=30), 1800.0, "exact")), \
         patch("src.integrations.auto_telemetry_preflight.probe_fit_time_range", return_value=(now, now + timedelta(minutes=30), 1800.0)):
        matched = resolve_telemetry_source_for_video(
            video_paths=[mp4],
            config={"auto_activity_source": "garmin"},
            provider_override=remote_mock,
        )

        assert matched == fit
        # Zero remote calls!
        remote_mock.connect.assert_not_called()
        remote_mock.list_activities.assert_not_called()
        remote_mock.download_telemetry.assert_not_called()


# ---------------------------------------------------------------------------
# 4. Priority 3: Asynchronous remote lookup & simulated network delay
# ---------------------------------------------------------------------------
def test_garmin_remote_lookup_async_with_delay(tmp_path):
    mp4 = tmp_path / "clip.mp4"
    mp4.write_bytes(b"mp4")

    now = datetime(2026, 10, 2, 10, 0, tzinfo=timezone.utc)
    cand = ActivityCandidate(
        activity_id="g101",
        provider="garmin",
        name="Garmin Ride",
        sport_type="cycling",
        start_dt=now,
        end_dt=now + timedelta(minutes=30),
        duration_s=1800.0,
        distance_m=15000.0,
    )

    downloaded = tmp_path / "downloaded.fit"
    downloaded.write_bytes(b"garmin_fit_data")

    remote_mock = MagicMock(spec=ActivityProvider)
    remote_mock.connect.return_value = True

    def slow_list(*args, **kwargs):
        # Simulate network latency
        time.sleep(0.1)
        return [cand]

    remote_mock.list_activities.side_effect = slow_list
    remote_mock.download_telemetry.return_value = downloaded

    matched_holder = []
    done_event = threading.Event()

    def on_matched(p: str, gen: int):
        matched_holder.append(p)
        done_event.set()

    with patch("src.multifile.probe_clip_time_interval", return_value=(now, now + timedelta(minutes=30), 1800.0, "exact")):
        # Synchronous resolve returns None immediately (does not block for network!)
        t0 = time.perf_counter()
        res = resolve_telemetry_source_for_video(
            video_paths=[mp4],
            config={"auto_activity_source": "garmin"},
            on_matched=on_matched,
            provider_override=remote_mock,
        )
        elapsed = time.perf_counter() - t0

        assert res is None
        # Call returned immediately without waiting for slow_list
        assert elapsed < 0.08

        # Background thread completes and delivers late telemetry
        assert done_event.wait(timeout=2.0)
        assert len(matched_holder) == 1
        assert matched_holder[0] == str(downloaded)


def test_strava_remote_lookup_async(tmp_path):
    mp4 = tmp_path / "clip.mp4"
    mp4.write_bytes(b"mp4")

    now = datetime(2026, 10, 2, 10, 0, tzinfo=timezone.utc)
    cand = ActivityCandidate(
        activity_id="s202",
        provider="strava",
        name="Strava Ride",
        sport_type="cycling",
        start_dt=now,
        end_dt=now + timedelta(minutes=30),
        duration_s=1800.0,
        distance_m=12000.0,
    )

    downloaded = tmp_path / "downloaded.gpx"
    downloaded.write_bytes(b"<gpx></gpx>")

    remote_mock = MagicMock(spec=ActivityProvider)
    remote_mock.connect.return_value = True
    remote_mock.list_activities.return_value = [cand]
    remote_mock.download_telemetry.return_value = downloaded

    matched_holder = []
    done_event = threading.Event()

    def on_matched(p: str, gen: int):
        matched_holder.append(p)
        done_event.set()

    with patch("src.multifile.probe_clip_time_interval", return_value=(now, now + timedelta(minutes=30), 1800.0, "exact")):
        res = resolve_telemetry_source_for_video(
            video_paths=[mp4],
            config={"auto_activity_source": "strava", "strava_client_id": "999"},
            on_matched=on_matched,
            provider_override=remote_mock,
        )
        assert res is None
        assert done_event.wait(timeout=2.0)
        assert matched_holder[0] == str(downloaded)


# ---------------------------------------------------------------------------
# 5. User not logged in -> remote skipped, zero modal popups
# ---------------------------------------------------------------------------
def test_remote_skipped_when_not_logged_in(tmp_path):
    mp4 = tmp_path / "clip.mp4"
    mp4.write_bytes(b"mp4")

    now = datetime(2026, 10, 2, 10, 0, tzinfo=timezone.utc)
    with patch("src.multifile.probe_clip_time_interval", return_value=(now, now + timedelta(minutes=30), 1800.0, "exact")), \
         patch("src.integrations.credential_store.get_garmin_tokens", return_value=None), \
         patch("src.integrations.credential_store.is_mock_mode", return_value=False), \
         patch("src.integrations.garmin_connect.GarminProvider") as mock_garmin_cls:

        res = resolve_telemetry_source_for_video(
            video_paths=[mp4],
            config={"auto_activity_source": "garmin"},
        )
        assert res is None
        # Not logged in: provider is never instantiated or contacted
        mock_garmin_cls.assert_not_called()


# ---------------------------------------------------------------------------
# 6. Zero cross-provider fallback
# ---------------------------------------------------------------------------
def test_zero_cross_provider_fallback_garmin_failure(tmp_path):
    mp4 = tmp_path / "clip.mp4"
    mp4.write_bytes(b"mp4")

    garmin_mock = MagicMock(spec=ActivityProvider)
    garmin_mock.connect.return_value = False  # Garmin fails

    with patch("src.multifile.probe_clip_time_interval", return_value=(datetime.now(timezone.utc), datetime.now(timezone.utc), 100.0, "exact")), \
         patch("src.integrations.strava.StravaProvider") as mock_strava:

        resolve_telemetry_source_for_video(
            video_paths=[mp4],
            config={"auto_activity_source": "garmin"},
            provider_override=garmin_mock,
        )
        time.sleep(0.1)

        # Zero Strava calls when Garmin fails!
        mock_strava.assert_not_called()


def test_zero_cross_provider_fallback_strava_failure(tmp_path):
    mp4 = tmp_path / "clip.mp4"
    mp4.write_bytes(b"mp4")

    strava_mock = MagicMock(spec=ActivityProvider)
    strava_mock.connect.return_value = False  # Strava fails

    with patch("src.multifile.probe_clip_time_interval", return_value=(datetime.now(timezone.utc), datetime.now(timezone.utc), 100.0, "exact")), \
         patch("src.integrations.garmin_connect.GarminProvider") as mock_garmin:

        resolve_telemetry_source_for_video(
            video_paths=[mp4],
            config={"auto_activity_source": "strava", "strava_client_id": "123"},
            provider_override=strava_mock,
        )
        time.sleep(0.1)

        # Zero Garmin calls when Strava fails!
        mock_garmin.assert_not_called()


# ---------------------------------------------------------------------------
# 7. Deduplication: at most 1 remote lookup per video
# ---------------------------------------------------------------------------
def test_deduplication_max_one_remote_lookup(tmp_path):
    mp4 = tmp_path / "clip.mp4"
    mp4.write_bytes(b"mp4")

    remote_mock = MagicMock(spec=ActivityProvider)
    remote_mock.connect.return_value = True

    block_event = threading.Event()

    def slow_list(*args, **kwargs):
        block_event.wait(timeout=1.0)
        return []

    remote_mock.list_activities.side_effect = slow_list

    with patch("src.multifile.probe_clip_time_interval", return_value=(datetime.now(timezone.utc), datetime.now(timezone.utc), 100.0, "exact")):
        # Call 1: launches remote search
        res1 = resolve_telemetry_source_for_video(
            video_paths=[mp4],
            config={"auto_activity_source": "garmin"},
            provider_override=remote_mock,
        )
        assert res1 is None

        # Call 2 with identical video paths while Call 1 is in-flight: deduplicated!
        res2 = resolve_telemetry_source_for_video(
            video_paths=[mp4],
            config={"auto_activity_source": "garmin"},
            provider_override=remote_mock,
        )
        assert res2 is None

        block_event.set()
        time.sleep(0.1)

        # list_activities called exactly once!
        assert remote_mock.list_activities.call_count == 1


# ---------------------------------------------------------------------------
# 8. Stale request rejection on video switch or clear
# ---------------------------------------------------------------------------
def test_stale_request_rejected_on_video_switch(tmp_path):
    mp4_a = tmp_path / "clip_a.mp4"
    mp4_a.write_bytes(b"a")
    mp4_b = tmp_path / "clip_b.mp4"
    mp4_b.write_bytes(b"b")

    now = datetime(2026, 10, 2, 10, 0, tzinfo=timezone.utc)
    cand_a = ActivityCandidate(
        activity_id="a1", provider="garmin", name="Ride A", sport_type="cycling",
        start_dt=now, end_dt=now + timedelta(minutes=30), duration_s=1800.0, distance_m=1000.0,
    )
    res_file_a = tmp_path / "result_a.fit"
    res_file_a.write_bytes(b"fit_a")

    remote_mock = MagicMock(spec=ActivityProvider)
    remote_mock.connect.return_value = True

    gate = threading.Event()

    def gated_download(*args, **kwargs):
        gate.wait(timeout=1.0)
        return res_file_a

    remote_mock.list_activities.return_value = [cand_a]
    remote_mock.download_telemetry.side_effect = gated_download

    matched_calls = []

    def on_matched(p: str, gen: int):
        matched_calls.append((p, gen))

    with patch("src.multifile.probe_clip_time_interval", return_value=(now, now + timedelta(minutes=30), 1800.0, "exact")):
        # User loads video A
        resolve_telemetry_source_for_video(
            video_paths=[mp4_a],
            config={"auto_activity_source": "garmin"},
            on_matched=on_matched,
            provider_override=remote_mock,
        )

        # While A is querying, user switches to video B
        orch = TelemetryOrchestrator.get_instance()
        orch.set_current_video_paths([mp4_b])

        # Release A's worker
        gate.set()
        time.sleep(0.15)

        # A's late attach was cancelled / rejected because video changed to B!
        assert matched_calls == []


def test_stale_request_rejected_on_clear(tmp_path):
    mp4 = tmp_path / "clip.mp4"
    mp4.write_bytes(b"a")

    now = datetime(2026, 10, 2, 10, 0, tzinfo=timezone.utc)
    cand = ActivityCandidate(
        activity_id="a1", provider="garmin", name="Ride", sport_type="cycling",
        start_dt=now, end_dt=now + timedelta(minutes=30), duration_s=1800.0, distance_m=1000.0,
    )
    res_file = tmp_path / "result.fit"
    res_file.write_bytes(b"fit")

    remote_mock = MagicMock(spec=ActivityProvider)
    remote_mock.connect.return_value = True

    gate = threading.Event()

    def gated_download(*args, **kwargs):
        gate.wait(timeout=1.0)
        return res_file

    remote_mock.list_activities.return_value = [cand]
    remote_mock.download_telemetry.side_effect = gated_download

    matched_calls = []

    def on_matched(p: str, gen: int):
        matched_calls.append((p, gen))

    with patch("src.multifile.probe_clip_time_interval", return_value=(now, now + timedelta(minutes=30), 1800.0, "exact")):
        resolve_telemetry_source_for_video(
            video_paths=[mp4],
            config={"auto_activity_source": "garmin"},
            on_matched=on_matched,
            provider_override=remote_mock,
        )

        # User clears project
        TelemetryOrchestrator.get_instance().on_project_cleared()

        gate.set()
        time.sleep(0.15)

        # Remote match ignored after clear!
        assert matched_calls == []


# ---------------------------------------------------------------------------
# 9. Manual override race handling
# ---------------------------------------------------------------------------
def test_manual_override_wins_over_inflight_remote(tmp_path):
    mp4 = tmp_path / "clip.mp4"
    mp4.write_bytes(b"mp4")
    manual_fit = tmp_path / "manual.fit"
    manual_fit.write_bytes(b"manual")

    now = datetime(2026, 10, 2, 10, 0, tzinfo=timezone.utc)
    cand = ActivityCandidate(
        activity_id="r9", provider="garmin", name="Ride", sport_type="cycling",
        start_dt=now, end_dt=now + timedelta(minutes=30), duration_s=1800.0, distance_m=1000.0,
    )
    res_remote = tmp_path / "remote.fit"
    res_remote.write_bytes(b"remote")

    remote_mock = MagicMock(spec=ActivityProvider)
    remote_mock.connect.return_value = True
    gate = threading.Event()

    def gated_download(*args, **kwargs):
        gate.wait(timeout=1.0)
        return res_remote

    remote_mock.list_activities.return_value = [cand]
    remote_mock.download_telemetry.side_effect = gated_download

    matched_calls = []

    def on_matched(p: str, gen: int):
        matched_calls.append(p)

    with patch("src.multifile.probe_clip_time_interval", return_value=(now, now + timedelta(minutes=30), 1800.0, "exact")):
        # Inflight remote starts
        resolve_telemetry_source_for_video(
            video_paths=[mp4],
            config={"auto_activity_source": "garmin"},
            on_matched=on_matched,
            provider_override=remote_mock,
        )

        # User manually selects a file while remote is still running
        orch = TelemetryOrchestrator.get_instance()
        orch.on_manual_telemetry_selected(manual_fit)

        # Remote finishes late
        gate.set()
        time.sleep(0.15)

        # Remote match was rejected because manual selection won!
        assert matched_calls == []
        assert orch.is_manual_selected() is True


# ---------------------------------------------------------------------------
# 10. Governance test: Project loading contains NO blocking remote network calls
# ---------------------------------------------------------------------------
def test_project_load_contains_no_blocking_remote_wait():
    """Verify that project_mixin.py contains no blocking req.completed.wait() or synchronous remote imports."""
    mixin_path = Path(__file__).resolve().parent.parent / "src" / "gui" / "qt" / "_mixins" / "project_mixin.py"
    content = mixin_path.read_text(encoding="utf-8")

    # Invariant: bg_load() must NEVER contain req.completed.wait(timeout=...)
    assert "req.completed.wait" not in content, "Found blocking req.completed.wait in project_mixin.py!"
    # Invariant: synchronous coordinator resolve_remote_activity must not be in project_mixin bg_load
    assert "resolve_remote_activity(" not in content, "Found synchronous resolve_remote_activity in project_mixin.py!"
