"""Regression tests for RenderProgressState scope and preflight error recovery.

Verifies:
1. RenderProgressState is resolved from module-level scope (no cellvar UnboundLocalError).
2. _on_render_requested succeeds past RenderProgressState initialization with a valid video path.
3. Preflight errors (missing video, nonexistent video, setup exceptions) cleanly emit terminal
   failed state, unlock the GUI state in RenderTab, and do not freeze on 0%.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import MagicMock

os.environ["QT_QPA_PLATFORM"] = "offscreen"

import pytest
from PySide6.QtWidgets import QApplication

from src.gui.qt.signals import get_signals
from src.gui.qt.controller import AppController
from src.gui.qt._mixins.render_mixin import RenderMixin
from src.render_progress import RenderProgressState


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication(sys.argv)
    yield app


def test_render_progress_state_scope_is_global_not_cellvar():
    """Verify that RenderProgressState is not trapped in co_cellvars / co_varnames."""
    code = RenderMixin._on_render_requested.__code__
    assert "RenderProgressState" not in code.co_cellvars, (
        "RenderProgressState must NOT be a cellvar; local imports in sub-branches create UnboundLocalError"
    )
    assert "RenderProgressState" not in code.co_varnames, (
        "RenderProgressState must NOT be a local var; it should be resolved from module globals"
    )
    assert "RenderProgressState" in code.co_names, (
        "RenderProgressState must be in co_names (global scope)"
    )


def test_on_render_requested_positive_scope_no_unbound_local(tmp_path, monkeypatch):
    """Positive test: with a valid existing MP4, _on_render_requested must initialize

    RenderProgressState without raising UnboundLocalError.
    """
    dummy_video = tmp_path / "valid_test.mp4"
    dummy_video.write_bytes(b"\x00" * 1024)

    s = get_signals()
    emitted_states: list[RenderProgressState] = []
    s.sig_render_state.connect(lambda snap: emitted_states.append(snap))

    ctrl = AppController()
    ctrl.video_path = dummy_video
    ctrl.video_paths = [dummy_video]

    # Mock _render_pipeline and worker thread start to avoid invoking hardware encoding in unit test
    worker_started = []

    def mock_thread_start(self_thread):
        worker_started.append(True)

    monkeypatch.setattr("threading.Thread.start", mock_thread_start)

    options = {
        "video_paths": [str(dummy_video)],
        "output": str(tmp_path / "out.mp4"),
        "encoder": "cpu",
        "render_mode": "cpu",
    }

    # Must NOT raise UnboundLocalError
    ctrl._on_render_requested(options)

    assert ctrl._render_latest_state is not None
    assert isinstance(ctrl._render_latest_state, RenderProgressState)
    assert ctrl._render_latest_state.state == "running"
    assert len(emitted_states) >= 1
    assert emitted_states[0].state == "running"
    assert len(worker_started) == 1


def test_on_render_requested_missing_video_emits_failed_terminal_state():
    """Missing video path must immediately emit failed terminal state so GUI is unlocked."""
    s = get_signals()
    emitted_states: list[RenderProgressState] = []
    errors: list[str] = []
    s.sig_render_state.connect(lambda snap: emitted_states.append(snap))
    s.sig_error.connect(lambda msg: errors.append(msg))

    ctrl = AppController()
    ctrl.video_path = None
    ctrl.video_paths = []

    options = {
        "video_paths": [],
        "output": "out.mp4",
        "_render_generation_id": 42,
    }

    ctrl._on_render_requested(options)

    assert len(emitted_states) >= 1
    fail_state = emitted_states[-1]
    assert fail_state.failed is True
    assert fail_state.state == "failed"
    assert fail_state.generation_id == 42
    assert len(errors) >= 1
    assert "Najpierw wybierz plik wideo" in errors[0]


def test_on_render_requested_nonexistent_video_file_emits_failed_terminal_state(tmp_path):
    """Nonexistent video file must immediately emit failed terminal state without deadlock."""
    s = get_signals()
    emitted_states: list[RenderProgressState] = []
    errors: list[str] = []
    s.sig_render_state.connect(lambda snap: emitted_states.append(snap))
    s.sig_error.connect(lambda msg: errors.append(msg))

    nonexistent = tmp_path / "missing_file_xyz.mp4"

    ctrl = AppController()
    ctrl.video_path = nonexistent
    ctrl.video_paths = [nonexistent]

    options = {
        "video_paths": [str(nonexistent)],
        "output": "out.mp4",
        "_render_generation_id": 99,
    }

    ctrl._on_render_requested(options)

    assert len(emitted_states) >= 1
    fail_state = emitted_states[-1]
    assert fail_state.failed is True
    assert fail_state.state == "failed"
    assert fail_state.generation_id == 99
    assert len(errors) >= 1
    assert "nie istnieje" in errors[0]


def test_render_tab_unlocks_on_failed_terminal_state(qapp):
    """RenderTab._on_render_state must end render and unlock controls when failed=True."""
    from src.gui.qt.tabs.render_tab import RenderTab

    tab = RenderTab()
    tab._render_generation_id = 123
    tab._rendering = True
    tab.btn_render.setEnabled(False)

    fail_snap = RenderProgressState(
        generation_id=123,
        state="failed",
        failed=True,
    )

    tab._on_render_state(fail_snap)

    assert tab._rendering is False
    assert tab.btn_render.isEnabled() is True
    assert "Błąd" in tab.lbl_stats.text()
