"""Unit tests for Common Render Preparation and RenderTelemetryCache."""

from datetime import datetime, timezone
from pathlib import Path
import numpy as np
import pytest

from src.render_telemetry_cache import RenderTelemetryCache, RenderTelemetryStatic
from src.render_preparation import RenderPreparationService


def test_render_telemetry_cache_columns_and_lookup(tmp_path: Path):
    """Verify columnar storage, memmap reload, and lookup parity."""
    total_frames = 100
    fps = 30.0
    frame_times = np.linspace(0.0, total_frames / fps, total_frames, dtype=np.float64)
    speed = np.sin(np.linspace(0, np.pi, total_frames)) * 30.0
    hr = np.full(total_frames, 145.0, dtype=np.float64)
    cad = np.full(total_frames, 85.0, dtype=np.float64)
    power = np.full(total_frames, 220.0, dtype=np.float64)

    base_dt = datetime(2026, 10, 2, 4, 26, 48, tzinfo=timezone.utc)
    static = RenderTelemetryStatic(
        start_dt_utc=base_dt,
        max_distance_m=12197.63,
        max_speed_kmh=45.2,
    )

    columns = {
        "frame_times": frame_times,
        "speed": speed,
        "std_hr": hr,
        "std_cad": cad,
        "std_power": power,
    }

    cache = RenderTelemetryCache(
        frames=total_frames,
        fps=fps,
        base_dt=base_dt,
        tz_offset_hours=0.0,
        columns=columns,
        string_tables={},
        static=static,
        cache_key="test_cache_key_1234",
    )

    manifest_path = cache.save(tmp_path)

    assert manifest_path.exists()
    assert (tmp_path / "columns.npz").exists()
    assert (tmp_path / "channels" / "speed.npy").exists()

    # Load via disk memmap
    loaded = RenderTelemetryCache.load(manifest_path, mmap=True)
    assert loaded.frames == total_frames
    assert loaded.fps == fps
    assert loaded.cache_key == "test_cache_key_1234"
    assert loaded.static.max_distance_m == 12197.63

    # Lookup frame 50
    rec50 = loaded.lookup(50)
    assert "speed_value" in rec50
    assert abs(rec50["speed_value"] - speed[50]) < 1e-4
    assert rec50["hr_value"] == 145.0
    assert rec50["cad_value"] == 85.0
    assert rec50["power_value"] == 220.0

    # Sequence / slicing parity
    assert len(loaded.records) == total_frames
    seq_rec50 = loaded.records[50]
    assert abs(seq_rec50["speed_value"] - speed[50]) < 1e-4


def test_cache_key_invariance_to_cosmetic_edits():
    """Verify that visual layout edits (x, y, font, color, etc.) do NOT invalidate cache key."""
    layout1 = {
        "indicators": {
            "speed_text": {"form": "gauge", "x": 10.0, "y": 20.0, "color": "#FFFFFF", "size": 1.0},
            "heart_rate": {"form": "text", "x": 50.0, "y": 80.0, "font": "Arial", "shadow": True},
        }
    }
    layout2 = {
        "indicators": {
            "speed_text": {"form": "gauge", "x": 15.0, "y": 25.0, "color": "#00FF00", "size": 1.5, "outline": True},
            "heart_rate": {"form": "text", "x": 55.0, "y": 85.0, "font": "Roboto", "shadow": False},
        }
    }

    dummy_video = Path("dummy_test_video.mp4")
    key1 = RenderPreparationService.compute_cache_key(
        video_paths=[dummy_video],
        total_frames=3000,
        target_fps=30.0,
        sync_offset_s=0.0,
        layout=layout1,
    )
    key2 = RenderPreparationService.compute_cache_key(
        video_paths=[dummy_video],
        total_frames=3000,
        target_fps=30.0,
        sync_offset_s=0.0,
        layout=layout2,
    )

    assert key1 == key2, "Cosmetic edits must yield identical cache keys!"


def test_cache_key_changes_on_sync_offset():
    """Verify that modifying sync offset invalidates the cache key."""
    layout = {"indicators": {"speed_text": {"form": "gauge"}}}
    dummy_video = Path("dummy_test_video.mp4")

    key_offset0 = RenderPreparationService.compute_cache_key(
        video_paths=[dummy_video],
        total_frames=3000,
        target_fps=30.0,
        sync_offset_s=0.0,
        layout=layout,
    )
    key_offset1 = RenderPreparationService.compute_cache_key(
        video_paths=[dummy_video],
        total_frames=3000,
        target_fps=30.0,
        sync_offset_s=1.5,
        layout=layout,
    )

    assert key_offset0 != key_offset1, "Changing sync offset must produce a different cache key!"
