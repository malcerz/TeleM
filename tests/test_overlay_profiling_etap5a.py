from __future__ import annotations

from src.indicators.profiling import OverlayProfiler


def test_overlay_profiler_is_disabled_by_default(monkeypatch) -> None:
    monkeypatch.delenv("AMD_OVERLAY_PROFILE", raising=False)
    profiler = OverlayProfiler()

    profiler.start_frame(0, 3840, 2160)
    profiler.record("compose.total", 12.0)
    profiler.finish_frame()

    assert profiler.summary() == {"enabled": False}


def test_overlay_profiler_aggregates_frames_and_geometry(monkeypatch) -> None:
    monkeypatch.setenv("AMD_OVERLAY_PROFILE", "ON")
    profiler = OverlayProfiler()
    # Pillow forwarding hooks are tested by the real export smoke/full runs.  Keep
    # this unit test isolated from process-global monkey-patching of Pillow.
    profiler._hooks_installed = True

    for frame, elapsed in enumerate((10.0, 20.0)):
        profiler.start_frame(frame, 3840, 2160)
        profiler.record("compose.total", elapsed)
        profiler.record_indicator_geometry(
            "speed", (100, 200, 300, 100), (300, 100), (3840, 2160), 1, "text"
        )
        profiler.finish_frame()

    summary = profiler.summary()
    assert summary["enabled"] is True
    assert summary["frames"] == 2
    assert summary["metrics"]["compose.total"]["avg_ms"] == 15.0
    assert summary["metrics"]["compose.total"]["median_ms"] == 15.0
    assert summary["geometry"]["speed"]["frames"] == 2
    assert summary["geometry"]["speed"]["render_width"] == 300
    assert summary["geometry"]["speed"]["render_height"] == 100

