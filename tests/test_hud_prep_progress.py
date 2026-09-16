"""Tests for central HUD preparation progress tracker."""
import time
import pytest
from src.render_progress import HudPrepProgressTracker, HudPhaseProfile


def test_hud_prep_progress_basic_monotonicity():
    events = []

    def on_progress(done, total, elapsed, fps, hud_state):
        events.append(hud_state.copy())

    tracker = HudPrepProgressTracker(
        phases=[
            ("phase_a", "Faza Pierwsza", 0.30),
            ("phase_b", "Faza Druga", 0.70),
        ],
        callback=on_progress,
        backend_name="TEST_BACKEND",
        global_prep_start_pct=0.0,
        global_prep_end_pct=10.0,
    )

    # Starts at 0%
    tracker.start_phase("phase_a", items_total=10)
    assert events[-1]["overall_hud_pct"] == 0.0
    assert events[-1]["phase_pct"] == 0.0
    assert events[-1]["work_done"] == 0
    assert events[-1]["work_total"] == 10
    assert "Faza Pierwsza" in events[-1]["label"]

    # Step through phase_a
    for i in range(1, 11):
        tracker.update(i, 10)

    # Phase A completed should give ~30%
    tracker.complete_phase("phase_a")
    assert pytest.approx(events[-1]["overall_hud_pct"], abs=1e-2) == 30.0
    assert events[-1]["work_done"] == 10

    # Start phase_b
    tracker.start_phase("phase_b", items_total=100)
    for i in range(1, 101):
        tracker.update(i, 100)

    profile = tracker.finish()
    assert events[-1]["overall_hud_pct"] == 100.0
    assert events[-1]["global_pct"] == 10.0
    assert "Gotowe" in events[-1]["label"]

    # Verify strict monotonicity across all emitted events
    last_pct = -1.0
    for ev in events:
        cur_pct = ev["overall_hud_pct"]
        assert cur_pct >= last_pct, f"Non-monotonic HUD progress: {cur_pct} < {last_pct}"
        last_pct = cur_pct

    assert profile["total_prep_ms"] >= 0.0
    assert len(profile["phases"]) == 2
    assert len(profile["slowest_3"]) == 2


def test_hud_prep_progress_skipped_phases_auto_complete():
    events = []

    def on_progress(done, total, elapsed, fps, hud_state):
        events.append(hud_state.copy())

    tracker = HudPrepProgressTracker(
        phases=[
            ("p1", "P1", 0.20),
            ("p2", "P2", 0.30),
            ("p3", "P3", 0.50),
        ],
        callback=on_progress,
    )

    tracker.start_phase("p1", items_total=5)
    tracker.update(5, 5)
    # Jump directly to p3 (p1 and p2 auto-completed upon start of p3)
    tracker.start_phase("p3", items_total=10)
    assert events[-1]["overall_hud_pct"] >= 50.0

    tracker.finish()
    assert events[-1]["overall_hud_pct"] == 100.0
    for ev in events:
        assert ev["overall_hud_pct"] >= 0.0
        assert ev["overall_hud_pct"] <= 100.0
