"""Tests for multi-file average speed calculation and preview/final parity.

Verifies:
1. test_multifile_preview_avg_respects_fit_pause:
   When camera has a gap and FIT timer was paused during the gap,
   active time freezes during the gap and matches ActiveTimeMapper.
2. test_multifile_preview_avg_keeps_running_without_fit_pause:
   When camera has a gap but FIT timer kept running,
   active time continues running across the gap even though video timeline is compressed.
3. test_multifile_preview_precompute_real_dataset_parity:
   Exact float parity between preview active_elapsed and precompute lookup.
"""

from datetime import datetime, timedelta
import os
import pytest

from pathlib import Path
from src.multifile import VideoTimeline, VideoClip
from src.telemetry_active_time import ActiveTimeMapper, compute_activity_distance_and_avg_speed


def test_multifile_preview_avg_respects_fit_pause():
    """Synthetic scenario with FIT pause during gap between clips:
    Activity start: 10:00
    Clip 1: 10:00 - 10:10 (600s)
    FIT pause: 10:10 - 10:20 (600s gap, timer stopped)
    Clip 2: 10:20 - 10:30 (600s)
    
    At end of Clip 2:
      wall clock = 30 min (1800s)
      video global timeline = 20 min (1200s)
      FIT active time = 20 min (1200s)
    """
    t0 = datetime(2026, 9, 1, 10, 0, 0)
    t1 = t0 + timedelta(minutes=10)
    t2 = t0 + timedelta(minutes=20)
    t3 = t0 + timedelta(minutes=30)
    
    # Pause interval during the gap: active is 10:00-10:10 and 10:20-10:30
    active_intervals = [(t0, t1), (t2, t3)]
    active_mapper = ActiveTimeMapper(
        active_intervals=active_intervals,
        start_dt=t0,
        end_dt=t3,
    )
    
    timeline = VideoTimeline([
        VideoClip(path=Path("clip1.mp4"), duration_s=600.0, absolute_start_dt=t0, timestamp_reliable=True),
        VideoClip(path=Path("clip2.mp4"), duration_s=600.0, absolute_start_dt=t2, timestamp_reliable=True),
    ])
    
    # Point at the end of clip 2 (global 1200s, absolute t3)
    target_dt = timeline.global_to_absolute(1200.0)
    assert target_dt == t3
    
    # Active elapsed time derived from absolute target_dt via ActiveTimeMapper
    active_elapsed = active_mapper.wall_to_active_seconds(target_dt)
    assert active_elapsed == 1200.0  # 20 min (pause of 10 min excluded)
    
    # Distance = 10,000 meters
    fit_samples = [
        (t0, 0.0),
        (t1, 5000.0),
        (t2, 5000.0),
        (t3, 10000.0),
    ]
    fit_data = {"distance": fit_samples, "active_time_mapper": active_mapper}
    
    # Preview calculation using absolute target_dt and active elapsed
    dist_m, preview_avg = compute_activity_distance_and_avg_speed(
        fit_data, None, None, target_dt, active_elapsed
    )
    assert dist_m == 10000.0
    # 10 km in 1200s (20 min = 1/3 h) -> 30.0 km/h
    assert pytest.approx(preview_avg, rel=1e-5) == 30.0


def test_multifile_preview_avg_keeps_running_without_fit_pause():
    """Synthetic scenario where FIT timer kept running across the gap between clips:
    Activity start: 10:00
    Clip 1: 10:00 - 10:10 (600s)
    Gap: 10:10 - 10:20 (600s, NO FIT PAUSE - bike computer continued recording)
    Clip 2: 10:20 - 10:30 (600s)
    
    At end of Clip 2:
      wall clock = 30 min (1800s)
      video global timeline = 20 min (1200s)
      FIT active time = 30 min (1800s)
    """
    t0 = datetime(2026, 9, 1, 10, 0, 0)
    t1 = t0 + timedelta(minutes=10)
    t2 = t0 + timedelta(minutes=20)
    t3 = t0 + timedelta(minutes=30)
    
    # NO pause intervals -> entire 30 min is active
    active_intervals = [(t0, t3)]
    active_mapper = ActiveTimeMapper(
        active_intervals=active_intervals,
        start_dt=t0,
        end_dt=t3,
    )
    
    timeline = VideoTimeline([
        VideoClip(path=Path("clip1.mp4"), duration_s=600.0, absolute_start_dt=t0, timestamp_reliable=True),
        VideoClip(path=Path("clip2.mp4"), duration_s=600.0, absolute_start_dt=t2, timestamp_reliable=True),
    ])
    
    # Point at the end of clip 2 (global 1200s, absolute t3)
    target_dt = timeline.global_to_absolute(1200.0)
    assert target_dt == t3
    
    # Active elapsed time derived from absolute target_dt via ActiveTimeMapper
    active_elapsed = active_mapper.wall_to_active_seconds(target_dt)
    assert active_elapsed == 1800.0  # 30 min (timer kept running during 10 min gap)
    
    # Distance = 10,000 meters
    fit_samples = [
        (t0, 0.0),
        (t1, 5000.0),
        (t2, 7000.0),  # rode 2km during the gap!
        (t3, 10000.0),
    ]
    fit_data = {"distance": fit_samples, "active_time_mapper": active_mapper}
    
    dist_m, preview_avg = compute_activity_distance_and_avg_speed(
        fit_data, None, None, target_dt, active_elapsed
    )
    assert dist_m == 10000.0
    # 10 km in 1800s (30 min = 0.5 h) -> 20.0 km/h
    assert pytest.approx(preview_avg, rel=1e-5) == 20.0


def test_multifile_preview_precompute_real_dataset_parity():
    """Verify exact float parity between preview active_elapsed and precompute lookup
    on real canonical multi-file files if present.
    """
    v1 = "Video/GX010114.MP4"
    v2 = "Video/GX010115.MP4"
    fit = "Video/GX010114_116.fit"
    if not (os.path.exists(v1) and os.path.exists(v2) and os.path.exists(fit)):
        pytest.skip("Benchmark files not present")
        
    from src.telemetry_precompute import build_telemetry_cache
    from src.multifile import build_timeline_from_paths
    from src.gui.telemetry_manager import TelemetryDataManager
    
    tm = TelemetryDataManager()
    tm.load_fit(str(fit))
    fit_mapper = getattr(tm.fit_data, "active_time_mapper", None)
    assert fit_mapper is not None
    
    timeline = build_timeline_from_paths([v1, v2], base_dt=tm.start_dt_utc)
    
    # Sample point inside Clip 2 (10s in)
    clip1_dur = timeline.clips[0].duration_s
    global_time = clip1_dur + 10.0
    fps = 30.0
    target_frame = int(round(global_time * fps))
    total_frames = target_frame + 2
    
    cache = build_telemetry_cache(
        total_frames=total_frames,
        target_fps=fps,
        update_rate_step=1,
        layout={"width": 1920, "height": 1080, "indicators": {}},
        base_dt=timeline.clips[0].absolute_start_dt,
        video_timeline=timeline,
        fit_data=tm.fit_data,
        tz_offset_hours=2.0,
        start_dt_utc=tm.start_dt_utc,
        speed_samples=tm.speed_samples or [],
        track_samples=tm.track_samples or [],
        alt_samples=tm.alt_samples or [],
    )
    
    rec = cache.lookup(target_frame)
    td_exact = rec["target_dt"]
    
    preview_active = fit_mapper.wall_to_active_seconds(td_exact)
    assert abs(preview_active - rec["elapsed_seconds"]) < 1e-9
    
    # Also verify preview prepare_overlay_frame_data produces exact float parity
    from src.indicators.frame_data import prepare_overlay_frame_data
    preview_data = prepare_overlay_frame_data(
        layout={"width": 1920, "height": 1080, "indicators": {}},
        target_dt=td_exact,
        tz_offset_hours=2.0,
        start_dt_utc=tm.start_dt_utc,
        speed_samples=tm.speed_samples or [],
        track_samples=tm.track_samples or [],
        alt_samples=tm.alt_samples or [],
        fit_data=tm.fit_data,
        total_frames=total_frames,
        current_index=int(global_time),
        project_elapsed_s=timeline.global_to_activity_elapsed(global_time),
    )
    
    assert abs(preview_data["elapsed_seconds"] - rec["elapsed_seconds"]) < 1e-9
    assert abs(preview_data["avg_speed_kmh"] - rec["avg_speed_kmh"]) < 1e-9



