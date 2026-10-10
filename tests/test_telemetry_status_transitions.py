import pytest
import threading
from datetime import datetime, timezone, timedelta
from pathlib import Path
from src.integrations.auto_telemetry_preflight import run_auto_telemetry_preflight
from src.integrations.activity_provider import ActivityProvider, ActivityCandidate

class MockGarminProviderFound(ActivityProvider):
    def get_provider_id(self) -> str: return "garmin"
    def is_authenticated(self) -> bool: return True
    def download_telemetry(self, activity_id, dest_dir):
        p = Path(dest_dir) / f"{activity_id}.fit"
        p.touch()
        return p
    def connect(self): return True
    def list_activities(self, start, end):
        actual_start = start + timedelta(hours=2)
        return [ActivityCandidate(activity_id="123", name="Ride", start_dt=actual_start, end_dt=actual_start+timedelta(seconds=600), sport_type="cycling", duration_s=600, provider="garmin")]
    def refresh_auth(self): pass
    def test_connection(self): return True

class MockGarminProviderNotFound(ActivityProvider):
    def get_provider_id(self) -> str: return "garmin"
    def is_authenticated(self) -> bool: return True
    def download_telemetry(self, activity_id, dest_dir):
        raise ValueError("Not found")
    def connect(self): return True
    def list_activities(self, start, end): return []
    def refresh_auth(self): pass
    def test_connection(self): return True
    
class MockGarminProviderNetworkError(ActivityProvider):
    def get_provider_id(self) -> str: return "garmin"
    def is_authenticated(self) -> bool: return True
    def download_telemetry(self, activity_id, dest_dir):
        pass
    def connect(self): return True
    def list_activities(self, start, end):
        raise ValueError("brak połączenia")
    def refresh_auth(self): pass
    def test_connection(self): return True

def test_status_transition_to_found(tmp_path, monkeypatch):
    video = tmp_path / "GX010001.MP4"
    video.touch()
    
    def mock_probe(*args, **kwargs):
        now = datetime.now(timezone.utc)
        return now, now + timedelta(seconds=600), 600.0, "mock"
    monkeypatch.setattr("src.multifile.probe_clip_time_interval", mock_probe)
    
    statuses = []
    def on_status(short, long, tooltip=None):
        statuses.append(short)
    
    run_auto_telemetry_preflight(
        video_paths=[str(video)],
        config={"auto_activity_source": "garmin"},
        on_status=on_status,
        provider_override=MockGarminProviderFound()
    )
    
    assert any("Wyszukiwanie lokalnych" in s for s in statuses)
    assert any("Wyszukiwanie aktywno" in s and "Garmin" in s for s in statuses)
    assert any("Pobieranie aktywno" in s for s in statuses)
    assert any("Znaleziono dopasowan" in s for s in statuses)

def test_status_transition_to_not_found(tmp_path, monkeypatch):
    video = tmp_path / "GX010001.MP4"
    video.touch()
    
    def mock_probe(*args, **kwargs):
        now = datetime.now(timezone.utc)
        return now, now + timedelta(seconds=600), 600.0, "mock"
    monkeypatch.setattr("src.multifile.probe_clip_time_interval", mock_probe)

    statuses = []
    def on_status(short, long, tooltip=None):
        statuses.append(short)
    
    run_auto_telemetry_preflight(
        video_paths=[str(video)],
        config={"auto_activity_source": "garmin"},
        on_status=on_status,
        provider_override=MockGarminProviderNotFound()
    )
    
    assert any("Wyszukiwanie lokalnych" in s for s in statuses)
    assert any("Wyszukiwanie aktywno" in s and "Garmin" in s for s in statuses)
    assert any("Nie znaleziono pasuj" in s for s in statuses)

def test_status_transition_network_error(tmp_path, monkeypatch):
    video = tmp_path / "GX010001.MP4"
    video.touch()
    
    def mock_probe(*args, **kwargs):
        now = datetime.now(timezone.utc)
        return now, now + timedelta(seconds=600), 600.0, "mock"
    monkeypatch.setattr("src.multifile.probe_clip_time_interval", mock_probe)

    statuses = []
    def on_status(short, long, tooltip=None):
        statuses.append(short)
    
    run_auto_telemetry_preflight(
        video_paths=[str(video)],
        config={"auto_activity_source": "garmin"},
        on_status=on_status,
        provider_override=MockGarminProviderNetworkError()
    )
    assert any("d sieci (Garmin Connect)" in s for s in statuses)

