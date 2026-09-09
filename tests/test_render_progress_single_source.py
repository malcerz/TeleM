"""Regression tests for one generation-tagged export progress source."""

from __future__ import annotations

import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from src.gui.qt.tabs.render_tab import RenderTab
from src.gui.qt.main_window import MainWindow
from src.gui.qt.widgets.video_preview import VideoPreview
from src.render_progress import RenderProgressState, format_render_progress_status
from src.render_progress import (
    RenderCancelReason,
    RenderCancelRequest,
    render_cancel_log_message,
)
from src.gui.qt._mixins.render_mixin import RenderMixin


def test_stale_cancelled_generation_cannot_replace_active_export_status():
    app = QApplication.instance() or QApplication(sys.argv)
    tab = RenderTab(preview=VideoPreview())
    tab._on_render()
    current_generation = tab._render_generation_id

    tab._on_render_state(RenderProgressState(
        generation_id=current_generation,
        state="rendering",
        frame=10330,
        total_frames=55649,
        percent=100.0 * 10330 / 55649,
        global_percent=18.0,
        elapsed_s=290.0,
        fps=35.7,
        eta_s=(55649 - 10330) / 35.7,
    ))
    expected = tab.lbl_stats.text()

    tab._on_render_state(RenderProgressState(
        generation_id=current_generation - 1,
        state="cancelled",
        frame=19,
        total_frames=55649,
        percent=0.0,
        elapsed_s=290.0,
        cancelled=True,
    ))

    assert tab.lbl_stats.text() == expected
    assert "10330" in tab.lbl_stats.text()
    assert "Anulowano" not in tab.lbl_stats.text()
    app.processEvents()


def test_cancel_requested_is_not_cancelled_until_terminal_state():
    snapshot = RenderProgressState(
        generation_id=7,
        state="cancelling",
        frame=10330,
        total_frames=55649,
        percent=18.57,
        elapsed_s=290.0,
        fps=35.7,
        eta_s=1260.0,
        cancel_requested=True,
    )
    text = format_render_progress_status(snapshot)
    assert "10330 / 55649" in text
    assert "Anulowanie..." in text
    assert "Anulowano" not in text


def test_render_state_status_uses_exporter_fps_and_eta():
    snapshot = RenderProgressState(
        generation_id=1,
        state="rendering",
        frame=10330,
        total_frames=55649,
        percent=18.57,
        elapsed_s=290.0,
        fps=35.7,
        eta_s=1260.0,
    )
    text = format_render_progress_status(snapshot)
    assert "18.6%" in text
    assert "FPS: 35.7" in text
    assert "ETA: 21:00" in text


def test_main_window_consumes_the_same_canonical_snapshot():
    app = QApplication.instance() or QApplication(sys.argv)
    window = MainWindow()
    snapshot = RenderProgressState(
        generation_id=41,
        state="rendering",
        frame=10330,
        total_frames=55649,
        percent=18.57,
        global_percent=18.57,
        elapsed_s=290.0,
        fps=35.7,
        eta_s=1260.0,
    )
    window._on_render_state(snapshot)
    assert "10330 / 55649" in window.status_label.text()
    assert "FPS: 35.7" in window.status_label.text()

    window._on_render_state(RenderProgressState(
        generation_id=40,
        state="cancelled",
        frame=19,
        total_frames=55649,
        cancelled=True,
    ))
    assert "10330 / 55649" in window.status_label.text()
    app.processEvents()


def test_new_render_has_fresh_cancel_event():
    class Harness(RenderMixin):
        pass

    harness = Harness()
    harness._begin_render_cancel_session(1)
    first = harness.render_cancel_event
    first.set()
    harness._begin_render_cancel_session(2)

    assert harness.render_cancel_event is not first
    assert not harness.render_cancel_event.is_set()
    assert harness._render_cancel_reason is RenderCancelReason.NONE


def test_preview_stop_does_not_cancel_render():
    app = QApplication.instance() or QApplication(sys.argv)
    tab = RenderTab(preview=VideoPreview())
    tab._on_render()
    requests = []
    tab.signals.sig_render_cancel_requested.connect(requests.append)

    tab._on_render_progress(10330, 55649, 290.0, 35.7, {"frame": 10330, "ts": 344.0})

    assert requests == []
    assert tab._rendering is True
    app.processEvents()


def test_old_generation_cancel_is_ignored():
    class Harness(RenderMixin):
        pass

    harness = Harness()
    harness._begin_render_cancel_session(2)
    harness._active_render_generation_id = 2

    changed = harness._set_render_cancel(
        generation_id=1,
        reason=RenderCancelReason.USER_CANCEL,
        source="STALE_WORKER",
    )

    assert changed is False
    assert not harness.render_cancel_event.is_set()
    assert harness._render_cancel_reason is RenderCancelReason.NONE


def test_internal_stop_is_not_reported_as_user_cancel():
    assert "Export cancelled by user" not in render_cancel_log_message(
        RenderCancelReason.INTERNAL_STOP
    )
    assert "reason=INTERNAL_STOP" in render_cancel_log_message(
        RenderCancelReason.INTERNAL_STOP
    )


def test_user_cancel_sets_user_reason():
    class Harness(RenderMixin):
        pass

    harness = Harness()
    harness._begin_render_cancel_session(7)
    harness._active_render_generation_id = 7
    harness._render_latest_state = RenderProgressState(generation_id=7, state="rendering")

    changed = harness._on_render_cancel_requested(RenderCancelRequest(
        generation_id=7,
        reason=RenderCancelReason.USER_CANCEL,
        source="GUI_BUTTON",
    ))

    assert changed is None
    assert harness.render_cancel_event.is_set()
    assert harness._render_cancel_reason is RenderCancelReason.USER_CANCEL
    assert harness._render_cancel_source == "GUI_BUTTON"
