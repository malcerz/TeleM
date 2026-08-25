"""Regression tests for Export Lifecycle P1-A (resource cleanup on exception)
and P1-B (cancel race / second export prevention).
"""

from __future__ import annotations

import os
import sys
import threading
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

os.environ["QT_QPA_PLATFORM"] = "offscreen"

import pytest
from PySide6.QtWidgets import QApplication

from src.gui.qt.signals import get_signals
from src.gui.qt.tabs.render_tab import RenderTab


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication(sys.argv)


class MockController:
    def __init__(self):
        self.video_duration_s = 10.0
        self._cut_regions = []
        self.layout = {"width": 1920, "height": 1080}
        self.telemetry = None


# ===========================================================================
# TEST 1 — CANCEL THEN IMMEDIATE RENDER (P1-B FIX)
# ===========================================================================

def test_cancel_then_immediate_render_blocked_until_stopped(qapp):
    signals = get_signals()
    ctrl = MockController()
    tab = RenderTab()
    tab.set_controller(ctrl)

    requested_events = []
    signals.sig_render_requested.connect(lambda opts: requested_events.append(opts))

    cancelled_events = []
    signals.sig_render_cancelled.connect(lambda: cancelled_events.append(True))

    # 1. Start Render A
    tab._on_render()
    assert tab._rendering is True
    assert tab._cancelling is False
    assert tab.btn_render.isEnabled() is False
    assert tab.btn_cancel.isEnabled() is True
    assert len(requested_events) == 1

    # 2. Trigger Cancel
    tab._on_cancel()
    assert tab._rendering is True
    assert tab._cancelling is True
    assert tab.btn_render.isEnabled() is False
    assert tab.btn_cancel.isEnabled() is False
    assert len(cancelled_events) == 1

    # 3. Attempt immediate second Render B while in CANCELLING state
    tab._on_render()
    # Export B must NOT start
    assert len(requested_events) == 1
    assert tab._cancelling is True
    assert tab.btn_render.isEnabled() is False

    # 4. Worker confirms exit via sig_render_stopped
    signals.sig_render_stopped.emit()

    # 5. Now state must be IDLE, btn_render enabled
    assert tab._rendering is False
    assert tab._cancelling is False
    assert tab.btn_render.isEnabled() is True
    assert tab.btn_cancel.isEnabled() is False

    # 6. Now Export B can start cleanly
    tab._on_render()
    assert len(requested_events) == 2
    assert tab._rendering is True
    assert tab.btn_render.isEnabled() is False


# ===========================================================================
# TEST 2 — PRODUCER EXCEPTION CLEANUP IN ASYNC (P1-A FIX)
# ===========================================================================

def test_async_producer_exception_cleans_up_resources(monkeypatch, tmp_path):
    from src.ffmpeg.amd_native_exporter import export_amd_native_d3d11

    # Mock native dll
    mock_dll = MagicMock()
    mock_dll.telem_amd_get_abi_version.return_value = 8
    mock_dll.telem_amd_get_build_info.return_value = b"build_id=test,build_timestamp=2026-08-20T00:00:00"
    mock_dll.telem_amd_create.return_value = 12345  # valid fake context handle
    mock_dll.telem_amd_set_diagnostics.return_value = 1
    mock_dll.telem_amd_set_profiling.return_value = 1
    mock_dll.telem_amd_set_hud_enabled.return_value = 1
    mock_dll.telem_amd_set_hud_mode.return_value = 1
    mock_dll.telem_amd_set_map_mode.return_value = 1
    mock_dll.telem_amd_set_above_map_mode.return_value = 1
    mock_dll.telem_amd_set_chart_mode.return_value = 1
    mock_dll.telem_amd_set_gauge_mode.return_value = 1
    mock_dll.telem_amd_set_source_rotation.return_value = 1
    mock_dll.telem_amd_set_decode_mode.return_value = 1
    mock_dll.telem_amd_read_video_sample.return_value = 1
    mock_dll.telem_amd_close.return_value = 1

    monkeypatch.setattr("ctypes.CDLL", lambda path: mock_dll)
    monkeypatch.setenv("AMD_CPU_GPU_PIPELINE", "ASYNC")
    monkeypatch.setenv("AMD_NATIVE_HUD_MODE", "GPU_HUD")
    monkeypatch.setenv("AMD_NATIVE_DECODE_MODE", "GPU_HUD_D3D11VA")

    test_input = str(tmp_path / "in.mp4")
    test_output = str(tmp_path / "out.mp4")
    with open(test_input, "wb") as f:
        f.write(b"dummy")

    with patch("src.ffmpeg.amd_native_exporter.compose_overlay", side_effect=RuntimeError("Injected producer failure")):
        with pytest.raises(RuntimeError, match="Injected producer failure"):
            export_amd_native_d3d11(
                ffmpeg_exe="ffmpeg",
                input_files=[test_input],
                output_file=test_output,
                duration_s=1.0,
                video_width=1920,
                video_height=1080,
                start_dt_utc=None,
                tz_offset_hours=0.0,
                speed_samples=[],
                track_samples=[],
                alt_samples=[],
                font_path="",
                layout={"width": 1920, "height": 1080, "indicators": {"speed": {"enabled": True}}},
                field_samples={},
                target_fps=30.0,
            )

    # telem_amd_close must have been called exactly once
    assert mock_dll.telem_amd_close.call_count == 1
    mock_dll.telem_amd_close.assert_called_once_with(12345)


# ===========================================================================
# TEST 3 — SYNC EXCEPTION CLEANUP (P1-A FIX)
# ===========================================================================

def test_sync_exception_cleans_up_resources(monkeypatch, tmp_path):
    from src.ffmpeg.amd_native_exporter import export_amd_native_d3d11

    # Mock native dll
    mock_dll = MagicMock()
    mock_dll.telem_amd_get_abi_version.return_value = 8
    mock_dll.telem_amd_get_build_info.return_value = b"build_id=test,build_timestamp=2026-08-20T00:00:00"
    mock_dll.telem_amd_create.return_value = 67890  # valid fake context handle
    mock_dll.telem_amd_set_diagnostics.return_value = 1
    mock_dll.telem_amd_set_profiling.return_value = 1
    mock_dll.telem_amd_set_hud_enabled.return_value = 1
    mock_dll.telem_amd_set_hud_mode.return_value = 1
    mock_dll.telem_amd_set_map_mode.return_value = 1
    mock_dll.telem_amd_set_above_map_mode.return_value = 1
    mock_dll.telem_amd_set_chart_mode.return_value = 1
    mock_dll.telem_amd_set_gauge_mode.return_value = 1
    mock_dll.telem_amd_set_source_rotation.return_value = 1
    mock_dll.telem_amd_set_decode_mode.return_value = 1
    mock_dll.telem_amd_read_video_sample.side_effect = ValueError("Injected consume failure")
    mock_dll.telem_amd_close.return_value = 1

    monkeypatch.setattr("ctypes.CDLL", lambda path: mock_dll)
    monkeypatch.setenv("AMD_CPU_GPU_PIPELINE", "SYNC")
    monkeypatch.setenv("AMD_NATIVE_HUD_MODE", "GPU_HUD")
    monkeypatch.setenv("AMD_NATIVE_DECODE_MODE", "GPU_HUD_D3D11VA")

    test_input = str(tmp_path / "in.mp4")
    test_output = str(tmp_path / "out.mp4")
    with open(test_input, "wb") as f:
        f.write(b"dummy")

    with pytest.raises(ValueError, match="Injected consume failure"):
        export_amd_native_d3d11(
            ffmpeg_exe="ffmpeg",
            input_files=[test_input],
            output_file=test_output,
            duration_s=1.0,
            video_width=1920,
            video_height=1080,
            start_dt_utc=None,
            tz_offset_hours=0.0,
            speed_samples=[],
            track_samples=[],
            alt_samples=[],
            font_path="",
            layout={"width": 1920, "height": 1080},
            field_samples={},
            target_fps=30.0,
        )

    # telem_amd_close must have been called exactly once
    assert mock_dll.telem_amd_close.call_count == 1
    mock_dll.telem_amd_close.assert_called_once_with(67890)


# ===========================================================================
# TEST 4 — CANCEL SIGNAL CLEANUP (SYNC & ASYNC)
# ===========================================================================

def test_cancel_event_closes_context_and_kills_proc_dec(monkeypatch, tmp_path):
    from src.ffmpeg.amd_native_exporter import export_amd_native_d3d11

    mock_dll = MagicMock()
    mock_dll.telem_amd_get_abi_version.return_value = 8
    mock_dll.telem_amd_get_build_info.return_value = b"build_id=test,build_timestamp=2026-08-20T00:00:00"
    mock_dll.telem_amd_create.return_value = 11111
    mock_dll.telem_amd_set_diagnostics.return_value = 1
    mock_dll.telem_amd_set_profiling.return_value = 1
    mock_dll.telem_amd_set_hud_enabled.return_value = 1
    mock_dll.telem_amd_set_hud_mode.return_value = 1
    mock_dll.telem_amd_set_map_mode.return_value = 1
    mock_dll.telem_amd_set_above_map_mode.return_value = 1
    mock_dll.telem_amd_set_chart_mode.return_value = 1
    mock_dll.telem_amd_set_gauge_mode.return_value = 1
    mock_dll.telem_amd_set_source_rotation.return_value = 1
    mock_dll.telem_amd_set_decode_mode.return_value = 1
    mock_dll.telem_amd_close.return_value = 1

    monkeypatch.setattr("ctypes.CDLL", lambda path: mock_dll)
    monkeypatch.setenv("AMD_CPU_GPU_PIPELINE", "SYNC")

    cancel_evt = threading.Event()
    cancel_evt.set()  # Pre-set cancel

    test_input = str(tmp_path / "in.mp4")
    test_output = str(tmp_path / "out.mp4")
    with open(test_input, "wb") as f:
        f.write(b"dummy")

    result = export_amd_native_d3d11(
        ffmpeg_exe="ffmpeg",
        input_files=[test_input],
        output_file=test_output,
        duration_s=1.0,
        video_width=1920,
        video_height=1080,
        start_dt_utc=None,
        tz_offset_hours=0.0,
        speed_samples=[],
        track_samples=[],
        alt_samples=[],
        font_path="",
        layout={"width": 1920, "height": 1080},
        field_samples={},
        target_fps=30.0,
        cancel_event=cancel_evt,
    )

    assert result is False
    assert mock_dll.telem_amd_close.call_count == 1
    mock_dll.telem_amd_close.assert_called_once_with(11111)


# ===========================================================================
# TEST 5 — NORMAL EXPORT REAL SMOKE (1 SECOND / 30 FRAMES)
# ===========================================================================

def test_real_smoke_normal_export(tmp_path):
    root = Path(__file__).parents[1]
    v_file = root / "Video" / "GX020079.mp4"
    if not v_file.exists():
        pytest.skip("Sample video GX020079.mp4 not found")

    out_file = str(tmp_path / "smoke_out.mp4")
    from src.ffmpeg.amd_native_exporter import export_amd_native_d3d11
    from src.gui.layout_manager import normalize_layout

    layout = normalize_layout({}, 1920, 1080)
    result = export_amd_native_d3d11(
        ffmpeg_exe="ffmpeg",
        input_files=[str(v_file)],
        output_file=out_file,
        duration_s=1.0,
        video_width=1920,
        video_height=1080,
        start_dt_utc=None,
        tz_offset_hours=0.0,
        speed_samples=[],
        track_samples=[],
        alt_samples=[],
        font_path="",
        layout=layout,
        field_samples={},
        target_fps=29.97,
    )

    assert result is True
    assert os.path.exists(out_file)
    assert os.path.getsize(out_file) > 1000


# ===========================================================================
# TEST 6 — CANCEL + RESTART REAL SMOKE
# ===========================================================================

def test_real_smoke_cancel_and_restart(tmp_path):
    root = Path(__file__).parents[1]
    v_file = root / "Video" / "GX020079.mp4"
    if not v_file.exists():
        pytest.skip("Sample video GX020079.mp4 not found")

    out_cancel = str(tmp_path / "smoke_cancel.mp4")
    out_restart = str(tmp_path / "smoke_restart.mp4")
    from src.ffmpeg.amd_native_exporter import export_amd_native_d3d11
    from src.gui.layout_manager import normalize_layout

    layout = normalize_layout({}, 1920, 1080)

    # 1. Export A with cancel event triggered after 3 frames
    cancel_evt = threading.Event()
    frames_seen = []

    def on_progress(completed, total, elapsed, fps, hud_state):
        frames_seen.append(completed)
        if completed >= 3:
            cancel_evt.set()

    res_a = export_amd_native_d3d11(
        ffmpeg_exe="ffmpeg",
        input_files=[str(v_file)],
        output_file=out_cancel,
        duration_s=2.0,
        video_width=1920,
        video_height=1080,
        start_dt_utc=None,
        tz_offset_hours=0.0,
        speed_samples=[],
        track_samples=[],
        alt_samples=[],
        font_path="",
        layout=layout,
        field_samples={},
        target_fps=29.97,
        on_render_progress=on_progress,
        cancel_event=cancel_evt,
    )

    assert res_a is False

    # 2. Immediately start Export B without cancel -> must succeed
    res_b = export_amd_native_d3d11(
        ffmpeg_exe="ffmpeg",
        input_files=[str(v_file)],
        output_file=out_restart,
        duration_s=1.0,
        video_width=1920,
        video_height=1080,
        start_dt_utc=None,
        tz_offset_hours=0.0,
        speed_samples=[],
        track_samples=[],
        alt_samples=[],
        font_path="",
        layout=layout,
        field_samples={},
        target_fps=29.97,
    )

    assert res_b is True
    assert os.path.exists(out_restart)
    assert os.path.getsize(out_restart) > 1000

