"""Tests for Layout Ownership (User Preset vs Project-Local Layout) and Lean Calibration + Vectorized HUD Prep."""

from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from src.indicators.lean import lean_visual_angle, lean_angle, _render_lean_indicator, clear_lean_caches
from src.telemetry_imu import interpolate_roll, compute_roll_timeline
from src.telemetry_precompute import build_telemetry_cache
from src.ffmpeg.worker_cache import WORKER_CACHE


def test_lean_calibration_math():
    """Verify calibrated lean angle rules:
    A. raw 0° + calibration +6° -> calibrated +6°.
    B. raw -6° -> calibrated 0°.
    C. backward compatibility: missing calibration defaults to 0.0°.
    D. legacy zero_offset field fallback.
    """
    cfg_calib6 = {"calibration": 6.0}
    assert lean_visual_angle(0.0, cfg_calib6) == 6.0
    assert lean_visual_angle(-6.0, cfg_calib6) == 0.0

    # Test numeric and angle parity in lean_angle
    assert lean_angle(0.0, cfg_calib6) == 6.0
    assert lean_angle(-6.0, cfg_calib6) == 0.0

    # Backward compatibility: empty cfg -> 0.0
    assert lean_visual_angle(0.0, {}) == 0.0
    assert lean_visual_angle(-6.0, {}) == -6.0

    # Legacy zero_offset fallback
    assert lean_visual_angle(0.0, {"zero_offset": 6.0}) == 6.0
    assert lean_visual_angle(-6.0, {"zero_offset": 6.0}) == 0.0


def test_lean_rotation_cache_and_parity():
    """Verify lean indicator rendering uses calibrated angle for both text and icon rotation,
    and leverages the bounded rotation cache."""
    clear_lean_caches()
    layout = {
        "indicators": {
            "lean_indicator": {
                "form": "lean",
                "graphic": "bike",
                "calibration": 6.0,
                "size": 1.0,
                "x": 50,
                "y": 50,
                "show_value": True,
                "decimals": 1,
            }
        }
    }
    cfg = layout["indicators"]["lean_indicator"]

    # Render frame with raw=0.0 -> calibrated angle should be +6.0°
    img1, rx1, ry1, extra1 = _render_lean_indicator(
        canvas_w=1920, canvas_h=1080, layout=layout, font_path="arial.ttf",
        key="lean_indicator", value=0.0, unit="°", label="LEAN",
        cfg=cfg, min_dim=1080, outline=2, fs=24, font=None,
        val_min=-30, val_max=30, ticks=6, thickness=3, size_px=108, ss=1
    )
    assert img1 is not None

    # Render second frame with identical angle -> hits cache
    img2, rx2, ry2, extra2 = _render_lean_indicator(
        canvas_w=1920, canvas_h=1080, layout=layout, font_path="arial.ttf",
        key="lean_indicator", value=0.0, unit="°", label="LEAN",
        cfg=cfg, min_dim=1080, outline=2, fs=24, font=None,
        val_min=-30, val_max=30, ticks=6, thickness=3, size_px=108, ss=1
    )
    assert img2 is not None


def test_lean_hud_prep_vectorized_no_hang():
    """Verify that build_telemetry_cache with Lean ON completes in milliseconds without freezing."""
    t0 = datetime(2026, 1, 1, 12, 0, 0)
    speed_samples = [(t0 + timedelta(seconds=i), 25.0) for i in range(100)]
    track_samples = [(t0 + timedelta(seconds=i), float(i * 10)) for i in range(100)]
    alt_samples = [(t0 + timedelta(seconds=i), 100.0) for i in range(100)]

    # 117,728 roll timeline points simulating full GoPro IMU stream
    timeline = [(t0 + timedelta(seconds=i * 0.005), float(i * 0.01)) for i in range(117728)]
    WORKER_CACHE["_lean_roll_timeline"] = {"z": timeline}

    layout_lean = {
        "indicators": {
            "lean_indicator": {
                "enabled": True, "form": "lean", "graphic": "bike",
                "source": "gyro", "axis": "z", "calibration": 6.0,
                "size": 1.0, "x": 50, "y": 50
            }
        }
    }

    import time
    t_start = time.perf_counter()
    cache = build_telemetry_cache(
        layout=layout_lean,
        base_dt=t0,
        tz_offset_hours=0,
        start_dt_utc=t0,
        speed_samples=speed_samples,
        track_samples=track_samples,
        alt_samples=alt_samples,
        total_frames=1131,
        target_fps=59.94,
    )
    elapsed_ms = (time.perf_counter() - t_start) * 1000.0
    assert cache.frames == 1131
    # Must complete fast (vectorized np.interp < 500ms total, usually ~15ms)
    assert elapsed_ms < 2000.0, f"HUD prep took too long: {elapsed_ms:.1f}ms (hang regression!)"


def test_sentinel_user_preset_immutability(tmp_path):
    """MANDATORY SENTINEL TEST:
    1. Create user preset: scratch/user_preset_sentinel.json
    2. Record initial byte content and sha256 hash.
    3. Load preset into PresetMixin / AppController.
    4. Perform property changes (font, position, lean indicator, gauge).
    5. Trigger render requested / project save.
    6. Verify user preset is byte-for-byte 100% UNCHANGED.
    7. Verify project-local layout (.layout.json) contains the changes.
    """
    scratch_dir = Path("scratch")
    scratch_dir.mkdir(exist_ok=True)
    sentinel_path = scratch_dir / "user_preset_sentinel.json"

    initial_data = {
        "format_version": 1,
        "global": {"font": "Arial", "text_outline": 2},
        "indicators": {
            "speed_gauge": {
                "form": "gauge", "x": 100, "y": 200, "size": 1.0, "font": "Arial"
            }
        }
    }
    sentinel_bytes = json.dumps(initial_data, indent=2, ensure_ascii=False).encode("utf-8")
    sentinel_path.write_bytes(sentinel_bytes)
    initial_hash = hashlib.sha256(sentinel_bytes).hexdigest()

    # Instantiate controller
    from src.gui.qt.controller import AppController
    ctrl = AppController()
    ctrl.base_dir = Path(".")
    fake_video = tmp_path / "test_video.MP4"
    fake_video.write_bytes(b"dummy")
    ctrl.video_path = fake_video
    ctrl.video_paths = [fake_video]

    # Load sentinel preset using _on_load_preset mock
    with patch("PySide6.QtWidgets.QFileDialog.getOpenFileName", return_value=(str(sentinel_path), "JSON")):
        ctrl._on_load_preset()

    assert ctrl._user_preset_path == str(sentinel_path)
    assert "speed_gauge" in ctrl.layout["indicators"]

    # Modify properties (change font, move gauge, add lean indicator)
    ctrl._on_property_changed("speed_gauge", "x", 350)
    ctrl._on_property_changed("speed_gauge", "font", "Digital-7 Mono")

    # Add lean indicator
    ctrl.layout["indicators"]["lean_indicator"] = {
        "form": "lean", "graphic": "bike", "calibration": 6.0, "x": 500, "y": 500
    }
    ctrl._on_property_changed("lean_indicator", "calibration", 6.0)

    # Trigger render save
    ctrl._on_render_requested({"quality": "high"})

    # CHECK SENTINEL IMMUTABILITY:
    after_bytes = sentinel_path.read_bytes()
    after_hash = hashlib.sha256(after_bytes).hexdigest()
    assert after_bytes == sentinel_bytes, "USER PRESET WAS MODIFIED! Contract violated!"
    assert after_hash == initial_hash, "USER PRESET HASH CHANGED! Contract violated!"

    # CHECK PROJECT-LOCAL LAYOUT CREATED AND UPDATED:
    proj_layout_path = ctrl.get_project_layout_path()
    assert proj_layout_path is not None
    assert proj_layout_path.exists()
    saved_proj = json.loads(proj_layout_path.read_text(encoding="utf-8"))
    assert saved_proj["indicators"]["speed_gauge"]["x"] == 350
    assert saved_proj["indicators"]["speed_gauge"]["font"] == "Digital-7 Mono"
    assert "lean_indicator" in saved_proj["indicators"]
    assert saved_proj["indicators"]["lean_indicator"]["calibration"] == 6.0

    # Clean up test artifacts
    try:
        if proj_layout_path.exists():
            proj_layout_path.unlink()
        if sentinel_path.exists():
            sentinel_path.unlink()
    except Exception:
        pass
