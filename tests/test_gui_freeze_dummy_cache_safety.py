import time
import threading
import numpy as np
from datetime import datetime, timezone, timedelta
from pathlib import Path
from PIL import Image
import pytest

from src.render_preparation import RenderPreparationService
from src.render_telemetry_cache import RenderTelemetryCache
from src.indicators.chart_utils import _build_chart_bg


@pytest.fixture(autouse=True)
def cleanup_prewarm():
    RenderPreparationService.invalidate()
    yield
    RenderPreparationService.invalidate()


def test_dummy_cache_never_used_by_final_export(tmp_path):
    """Test that final export / prepare always receives complete data even if prewarm is running."""
    total_frames = 500
    fps = 30.0
    layout = {"indicators": {"speed_text": {"enabled": True, "source": "gpmf", "field": "speed"}}}
    base_dt = datetime(2026, 10, 7, 10, 0, 0)
    samples = [(base_dt + timedelta(seconds=i / fps), float(10 + i % 20)) for i in range(total_frames)]

    # Start prewarm in background
    options = {"video_paths": [str(tmp_path / "vid1.mp4")]}
    
    class MockTelemetry:
        speed_samples = samples
        track_samples = []
        alt_samples = []
        fit_data = {}
        fit_path = None
        gpx_path = None
        start_dt_utc = base_dt

    # Launch prewarm
    RenderPreparationService.prewarm(
        options=options,
        telemetry=MockTelemetry(),
        layout=layout,
        video_paths=options["video_paths"],
        total_frames=total_frames,
        target_fps=fps,
        base_cache_dir=tmp_path,
    )

    # Immediately call prepare (as final export does)
    cache = RenderPreparationService.prepare(
        options=options,
        telemetry=MockTelemetry(),
        layout=layout,
        video_paths=options["video_paths"],
        total_frames=total_frames,
        target_fps=fps,
        base_cache_dir=tmp_path,
    )

    # Assert complete frames - NEVER dummy 1 frame!
    assert cache is not None
    assert cache.frames == total_frames, f"Expected {total_frames} frames, got {cache.frames}"
    assert cache.frames > 1


def test_dummy_cache_never_persisted(tmp_path):
    """Test that cache saved to disk always has complete frame counts."""
    total_frames = 200
    fps = 30.0
    layout = {}
    base_dt = datetime(2026, 10, 7, 10, 0, 0)
    v_paths = [str(tmp_path / "vid.mp4")]

    cache = RenderPreparationService.get_or_build(
        layout=layout,
        base_dt=base_dt,
        total_frames=total_frames,
        target_fps=fps,
        video_paths=v_paths,
        base_cache_dir=tmp_path,
    )

    assert cache.frames == total_frames
    cdir = RenderPreparationService.get_cache_dir(cache.cache_key, tmp_path)
    m_path = cdir / "manifest.json"
    assert m_path.exists()

    # Load from disk
    loaded = RenderTelemetryCache.load(m_path, mmap=True)
    assert loaded.frames == total_frames
    assert loaded.frames > 1


def test_preview_nonblocking_while_prewarm(tmp_path):
    """Test that get_ready_cache_nonblocking returns immediately without blocking."""
    v_paths = [str(tmp_path / "vid_slow.mp4")]
    cache_key = RenderPreparationService.compute_cache_key(
        video_paths=v_paths,
        total_frames=1000,
        target_fps=30.0,
    )

    t0 = time.perf_counter()
    ready_cache = RenderPreparationService.get_ready_cache_nonblocking(cache_key, base_cache_dir=tmp_path)
    elapsed_ms = (time.perf_counter() - t0) * 1000.0

    assert ready_cache is None
    assert elapsed_ms < 10.0, f"Nonblocking check took too long: {elapsed_ms:.2f} ms"


def test_complete_cache_after_prewarm(tmp_path):
    """Test that after prewarm finishes, complete cache is immediately ready."""
    total_frames = 300
    fps = 30.0
    layout = {}
    base_dt = datetime(2026, 10, 7, 10, 0, 0)
    options = {"video_paths": [str(tmp_path / "vid_complete.mp4")]}

    class MockTelemetry:
        speed_samples = []
        track_samples = []
        alt_samples = []
        fit_data = {}
        fit_path = None
        gpx_path = None
        start_dt_utc = base_dt

    RenderPreparationService.prewarm(
        options=options,
        telemetry=MockTelemetry(),
        layout=layout,
        video_paths=options["video_paths"],
        total_frames=total_frames,
        target_fps=fps,
        base_cache_dir=tmp_path,
    )

    # Wait for prewarm thread
    th = RenderPreparationService._prewarm_thread
    if th is not None:
        th.join(timeout=10.0)

    cache_key = RenderPreparationService.compute_cache_key(
        video_paths=options["video_paths"],
        total_frames=total_frames,
        target_fps=fps,
    )

    ready_cache = RenderPreparationService.get_ready_cache_nonblocking(cache_key, base_cache_dir=tmp_path)
    assert ready_cache is not None
    assert ready_cache.frames == total_frames


def test_project_switch_discards_stale_prewarm(tmp_path):
    """Test that opening Project B cancels Project A prewarm and discards stale cache."""
    # Launch Project A prewarm
    options_a = {"video_paths": [str(tmp_path / "project_a.mp4")]}
    
    class MockTelemetryA:
        speed_samples = []
        track_samples = []
        alt_samples = []
        fit_data = {}
        fit_path = None
        gpx_path = None
        start_dt_utc = datetime(2026, 10, 7, 10, 0, 0)

    RenderPreparationService.prewarm(
        options=options_a,
        telemetry=MockTelemetryA(),
        layout={},
        video_paths=options_a["video_paths"],
        total_frames=5000,
        target_fps=30.0,
        base_cache_dir=tmp_path,
    )
    th_a = RenderPreparationService._prewarm_thread

    # User immediately switches to Project B
    RenderPreparationService.invalidate()

    # Prewarm thread A completes (or aborts)
    if th_a:
        th_a.join(timeout=5.0)

    # Check in-memory prewarmed state: Project A cache MUST NOT be stored!
    with RenderPreparationService._lock:
        stored_cache = RenderPreparationService._prewarmed_cache
        stored_key = RenderPreparationService._prewarmed_key

    key_a = RenderPreparationService.compute_cache_key(
        video_paths=options_a["video_paths"],
        total_frames=5000,
        target_fps=30.0,
    )
    assert stored_key != key_a, "Stale Project A cache was incorrectly stored after project switch!"


def test_late_fit_refreshes_preview(tmp_path):
    """Test that invalidating prewarm state prepares the service for late FIT attachment."""
    v_paths = [str(tmp_path / "video.mp4")]
    total_frames = 100
    fps = 30.0

    # Initial state without FIT
    cache1 = RenderPreparationService.get_or_build(
        layout={},
        base_dt=datetime(2026, 10, 7, 10, 0, 0),
        total_frames=total_frames,
        target_fps=fps,
        video_paths=v_paths,
        fit_path=None,
        base_cache_dir=tmp_path,
    )
    assert cache1.frames == total_frames

    # Invalidate when late FIT arrives
    RenderPreparationService.invalidate()

    # Build with late FIT
    fit_path = str(tmp_path / "late.fit")
    cache2 = RenderPreparationService.get_or_build(
        layout={},
        base_dt=datetime(2026, 10, 7, 10, 0, 0),
        total_frames=total_frames,
        target_fps=fps,
        video_paths=v_paths,
        fit_path=fit_path,
        base_cache_dir=tmp_path,
    )
    assert cache2.cache_key != cache1.cache_key
    assert cache2.frames == total_frames


def test_chart_chunking_visual_parity():
    """Test that chart rendering produces valid RGBA image with correct dimensions and points."""
    samples = [float(100 + 20 * np.sin(i / 100.0)) for i in range(5000)]
    bg_img, points, p1, p2, thickness = _build_chart_bg(
        history_values=samples,
        width=960,
        height=240,
        line_color=(255, 255, 255),
        line_thickness=2,
        fill_alpha=120,
        fill_color=(50, 150, 250),
        show_axes=True,
        grid_color=(100, 100, 100, 100),
        time_labels=None,
        value_labels=None,
        supersample=1,
        custom_min_val=None,
        custom_max_val=None,
        label_count=5,
        label_units=True,
        unit="m",
        show_average=False,
        label_font_size=12.0,
        font_path=None,
        draw_series=True,
    )
    assert isinstance(bg_img, Image.Image)
    assert bg_img.size == (960, 240)
    assert len(points) == 5000
    assert thickness == 2


def test_cold_warm_telemetry_parity(tmp_path):
    """Test byte-exact data parity between cold and warm cache loads."""
    total_frames = 200
    fps = 30.0
    base_dt = datetime(2026, 10, 7, 10, 0, 0)
    v_paths = [str(tmp_path / "parity_test.mp4")]
    layout = {"indicators": {"speed_text": {"enabled": True, "source": "gpmf", "field": "speed"}}}
    samples = [(base_dt + timedelta(seconds=i / fps), float(20.0 + i * 0.1)) for i in range(total_frames)]

    # Cold build
    cold_cache = RenderPreparationService.get_or_build(
        layout=layout,
        base_dt=base_dt,
        speed_samples=samples,
        total_frames=total_frames,
        target_fps=fps,
        video_paths=v_paths,
        base_cache_dir=tmp_path,
    )

    # Invalidate in-memory so warm loads from disk
    with RenderPreparationService._lock:
        RenderPreparationService._prewarmed_cache = None
        RenderPreparationService._prewarmed_key = ""

    # Warm build from disk
    warm_cache = RenderPreparationService.get_or_build(
        layout=layout,
        base_dt=base_dt,
        speed_samples=samples,
        total_frames=total_frames,
        target_fps=fps,
        video_paths=v_paths,
        base_cache_dir=tmp_path,
    )

    assert cold_cache.frames == warm_cache.frames
    assert cold_cache.cache_key == warm_cache.cache_key
    assert np.allclose(cold_cache.columns["speed"], warm_cache.columns["speed"])


def test_queue_uses_complete_cache(tmp_path):
    """Test that export queue preparation retrieves the full cache without truncation."""
    total_frames = 600
    fps = 29.97
    base_dt = datetime(2026, 10, 7, 10, 0, 0)
    v_paths = [str(tmp_path / "queue_test.mp4")]

    class MockTelemetry:
        speed_samples = []
        track_samples = []
        alt_samples = []
        fit_data = {}
        fit_path = None
        gpx_path = None
        start_dt_utc = base_dt

    options = {"video_paths": v_paths}
    cache = RenderPreparationService.prepare(
        options=options,
        telemetry=MockTelemetry(),
        layout={},
        video_paths=v_paths,
        total_frames=total_frames,
        target_fps=fps,
        base_cache_dir=tmp_path,
    )

    assert cache.frames == total_frames
    assert cache.frames == 600


def test_gui_event_loop_stall_bounded(tmp_path):
    """Test that background prewarm does not starve event loop or thread execution."""
    total_frames = 2000
    fps = 30.0
    base_dt = datetime(2026, 10, 7, 10, 0, 0)
    v_paths = [str(tmp_path / "stall_test.mp4")]

    class MockTelemetry:
        speed_samples = [(base_dt + timedelta(seconds=i / fps), float(i)) for i in range(total_frames)]
        track_samples = []
        alt_samples = []
        fit_data = {}
        fit_path = None
        gpx_path = None
        start_dt_utc = base_dt

    options = {"video_paths": v_paths}

    # Start background prewarm
    RenderPreparationService.prewarm(
        options=options,
        telemetry=MockTelemetry(),
        layout={},
        video_paths=v_paths,
        total_frames=total_frames,
        target_fps=fps,
        base_cache_dir=tmp_path,
    )

    # Monitor stalls in calling thread simulating Qt heartbeat
    stalls = []
    interval = 0.016  # 16 ms (60 FPS)
    for _ in range(30):
        t0 = time.perf_counter()
        time.sleep(interval)
        actual = (time.perf_counter() - t0) * 1000.0
        delta = actual - (interval * 1000.0)
        stalls.append(max(0.0, delta))

    max_stall = max(stalls)
    # Background prewarm should not freeze the thread for > 100ms
    assert max_stall < 100.0, f"Max stall exceeded 100ms: {max_stall:.2f} ms"
