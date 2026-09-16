"""Unit tests for RT quality & compression analysis formatting in GUI."""

from __future__ import annotations

import os
import sys

os.environ["QT_QPA_PLATFORM"] = "offscreen"

import pytest
from PySide6.QtWidgets import QApplication

from src.gui.qt._mixins.render_mixin import RenderMixin
from src.gui.qt.signals import get_signals
from src.render_progress import RenderProgressState


class MockController(RenderMixin):
    def __init__(self) -> None:
        self.signals = get_signals()
        self.video_path = "dummy.mp4"
        self._active_render_generation_id = 1
        self._render_generation_counter = 1
        self._render_cancel_reason = None
        self._render_cancel_source = ""
        self._render_session_start = 0.0

    def _render_pipeline(self, options: dict) -> dict:
        return {}


def test_rt_compression_display_live_and_completed():
    app = QApplication.instance() or QApplication(sys.argv)
    ctrl = MockController()
    emitted_states: list[RenderProgressState] = []
    ctrl.signals.sig_render_state.connect(emitted_states.append)

    # Initialize render session callbacks
    ctrl._on_render_requested({"_render_generation_id": 1, "render_mode": "gpu", "encoder": "nv"})
    
    # Simulate on_render_progress during live render (HEVC)
    hud_state_live = {
        "phase": "render",
        "compression_active": True,
        "is_av1": False,
        "current_qp": 18,
        "mean_qp": 26.12,
        "p90_qp": 31.0,
        "bitrate_mbps": 36.4,
    }
    ctrl._emit_render_progress_callback(500, 1000, 10.0, 50.0, hud_state_live)

    assert len(emitted_states) >= 1
    live_state = emitted_states[-1]
    assert live_state.compression_text == "QP śr: 26.1 | P90: 31 | q teraz: 18 | 36.4 Mbps"

    # Simulate completion
    ctrl._emit_render_terminal_state("completed")
    completed_state = emitted_states[-1]
    assert completed_state.compression_text == "QP śr: 26.1 | P90: 31 | 36.4 Mbps"
    assert "q teraz" not in completed_state.compression_text


def test_rt_compression_display_av1_live_and_completed():
    app = QApplication.instance() or QApplication(sys.argv)
    ctrl = MockController()
    emitted_states: list[RenderProgressState] = []
    ctrl.signals.sig_render_state.connect(emitted_states.append)

    ctrl._on_render_requested({"_render_generation_id": 2, "render_mode": "gpu", "encoder": "nv"})

    # Simulate on_render_progress during live render (AV1)
    hud_state_av1 = {
        "phase": "render",
        "compression_active": True,
        "is_av1": True,
        "current_qp": 38,
        "mean_qp": 42.77,
        "p90_qp": 52.0,
        "bitrate_mbps": 42.6,
    }
    ctrl._emit_render_progress_callback(500, 1000, 10.0, 50.0, hud_state_av1)

    live_state = emitted_states[-1]
    assert live_state.compression_text == "QIndex śr: 42.8 | P90: 52 | q teraz: 38 | 42.6 Mbps"

    # Simulate completion
    ctrl._emit_render_terminal_state("completed")
    completed_state = emitted_states[-1]
    assert completed_state.compression_text == "QIndex śr: 42.8 | P90: 52 | 42.6 Mbps"
    assert "q teraz" not in completed_state.compression_text
