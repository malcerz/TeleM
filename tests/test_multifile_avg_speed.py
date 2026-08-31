"""Tests for multi-file activity-global average speed calculation.

Ensures that average speed uses activity-global cumulative distance divided by
activity-global elapsed time, avoiding denominator resets or clip-local timer
mismatches at multi-file clip boundaries (e.g. GX010114 -> GX010115 -> GX010116).
"""

import pytest
from datetime import datetime, timedelta
from src.indicators.frame_data import prepare_overlay_frame_data
from src.telemetry_precompute import build_telemetry_cache
from src.multifile import build_timeline_from_paths, VideoTimeline, VideoClip
from pathlib import Path


def _create_synthetic_layout():
    return {
        "width": 1920,
        "height": 1080,
        "indicators": {
            "time_display": {
                "enabled": True,
                "x": 0.05,
                "y": 0.05,
                "show_date": True,
                "show_time": True,
                "show_elapsed": True,
                "show_avg_speed": True,
            },
            "dist_text": {
                "enabled": True,
                "source": "fit",
            }
        }
    }


def test_multifile_avg_speed_activity_elapsed_continuity():
    """Verify average speed stays continuous across clip transitions and does not reset to 0 or explode."""
    layout = _create_synthetic_layout()
    start_dt = datetime(2026, 8, 14, 9, 40, 10)
    
    # 3 clips: 014 (0..1956s), 015 (gap 65min, 11:18:02..11:27:54), 016 (11:32:09..12:01:13)
    c0 = VideoClip(path=Path("GX010114.MP4"), duration_s=1956.0, absolute_start_dt=datetime(2026, 8, 14, 9, 40, 11))
    c1 = VideoClip(path=Path("GX010115.MP4"), duration_s=592.0, absolute_start_dt=datetime(2026, 8, 14, 11, 18, 2))
    c2 = VideoClip(path=Path("GX010116.MP4"), duration_s=1743.0, absolute_start_dt=datetime(2026, 8, 14, 11, 32, 9))
    timeline = VideoTimeline.from_clips([c0, c1, c2], base_dt=start_dt)
    
    # Synthetic FIT data:
    # 09:40:10 -> 0m
    # 10:12:47 -> 12080m
    # 11:18:02 -> 12080m (paused during gap)
    # 11:18:28 -> 12134m (26s into clip 1)
    # 11:27:54 -> 15020m (end of clip 1)
    fit_samples = [
        (datetime(2026, 8, 14, 9, 40, 10), 0.0),
        (datetime(2026, 8, 14, 10, 12, 47), 12080.0),
        (datetime(2026, 8, 14, 11, 18, 2), 12080.0),
        (datetime(2026, 8, 14, 11, 18, 28), 12134.47),
        (datetime(2026, 8, 14, 11, 27, 54), 15020.0),
        (datetime(2026, 8, 14, 11, 32, 10), 15020.0),
        (datetime(2026, 8, 14, 12, 1, 12), 24230.0),
    ]
    fit_data = {"distance": fit_samples, "speed": [(s[0], 25.0) for s in fit_samples]}
    
    # Test Clip 1 at local 26s (the bug point):
    target_dt_26 = datetime(2026, 8, 14, 11, 18, 28)
    data_26 = prepare_overlay_frame_data(
        layout=layout,
        target_dt=target_dt_26,
        tz_offset_hours=2,
        start_dt_utc=datetime(2026, 8, 14, 11, 18, 2), # Clip-local GPMF start passed to preview
        speed_samples=[],
        track_samples=[],
        alt_samples=[],
        fit_data=fit_data,
        total_frames=1000,
        current_index=1982,
    )
    
    # Distance is ~12.13 km
    assert data_26["distance_m"] == pytest.approx(12134.47, abs=1.0)
    # Elapsed seconds in activity = 5898s (not 26s!)
    # Average speed must be ~7.4 km/h, NEVER ~1680 km/h!
    assert 7.0 <= data_26["avg_speed_kmh"] <= 8.0
    assert data_26["avg_speed_kmh"] < 50.0


def test_single_file_avg_speed():
    """Verify single file average speed works correctly."""
    layout = _create_synthetic_layout()
    start_dt = datetime(2026, 8, 14, 9, 0, 0)
    
    fit_samples = [
        (datetime(2026, 8, 14, 9, 0, 0), 0.0),
        (datetime(2026, 8, 14, 9, 10, 0), 5000.0), # 5 km in 600s = 30 km/h
    ]
    fit_data = {"distance": fit_samples}
    
    target_dt = datetime(2026, 8, 14, 9, 10, 0)
    data = prepare_overlay_frame_data(
        layout=layout,
        target_dt=target_dt,
        tz_offset_hours=2,
        start_dt_utc=start_dt,
        speed_samples=[],
        track_samples=[],
        alt_samples=[],
        fit_data=fit_data,
        total_frames=600,
        current_index=600,
    )
    
    assert data["distance_m"] == 5000.0
    assert data["avg_speed_kmh"] == pytest.approx(30.0, abs=0.1)
