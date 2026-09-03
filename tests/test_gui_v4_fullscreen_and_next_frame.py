"""Automated verification suite for TELEM GUI v4:
1. NEXT FRAME & PREVIOUS FRAME (integer domain, exact seek, 10x NEXT, 10x PREVIOUS, multi-file boundary).
2. FULLSCREEN PREVIEW LIFECYCLE & OWNERSHIP (takeCentralWidget, shiboken6.isValid, 20x cycles, ESC exit).
"""

import os
import sys
from pathlib import Path
from unittest.mock import MagicMock

# Offscreen Qt
os.environ["QT_QPA_PLATFORM"] = "offscreen"
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt
from PySide6.QtGui import QKeyEvent
from shiboken6 import isValid

app = QApplication.instance() or QApplication([])

from src.gui.qt.controller import AppController
from src.gui.qt.main_window import MainWindow
from src.multifile import VideoClip, VideoTimeline


def test_fullscreen_enter_does_not_destroy_normal_central():
    """A. Fullscreen enter nie niszczy normal central widget (tabs)."""
    win = MainWindow()
    ctrl = AppController()
    win.set_controller(ctrl)
    win.show()

    tabs_ref = win.tabs
    assert isValid(tabs_ref), "tabs must be valid initially"
    assert win.centralWidget() is tabs_ref

    win.enter_fullscreen_preview()

    assert isValid(tabs_ref), "tabs must remain valid after enter_fullscreen_preview"
    assert win.centralWidget() is win.preview
    assert win._preview_fullscreen is True


def test_fullscreen_exit_restores_same_qtabwidget():
    """B. Fullscreen exit przywraca TEN SAM obiekt QTabWidget."""
    win = MainWindow()
    ctrl = AppController()
    win.set_controller(ctrl)
    win.show()

    original_tabs = win.tabs
    original_preview = win.preview

    win.enter_fullscreen_preview()
    assert win.centralWidget() is original_preview

    win.exit_fullscreen_preview()
    assert win.centralWidget() is original_tabs
    assert win.tabs is original_tabs
    assert isValid(original_tabs), "tabs C++ object must not be deleted"
    assert isValid(original_preview), "preview C++ object must not be deleted"
    assert win._preview_fullscreen is False


def test_fullscreen_twenty_toggle_cycles():
    """C. 20 toggle cycles (normal -> fullscreen -> normal) with shiboken6.isValid validation."""
    win = MainWindow()
    ctrl = AppController()
    win.set_controller(ctrl)
    win.show()

    tabs_ref = win.tabs
    preview_ref = win.preview

    for cycle in range(1, 21):
        # Enter
        win.toggle_fullscreen_preview()
        assert win._preview_fullscreen is True, f"Cycle {cycle}: state must be fullscreen"
        assert win.centralWidget() is preview_ref, f"Cycle {cycle}: central must be preview"
        assert isValid(tabs_ref), f"Cycle {cycle}: tabs destroyed during enter!"
        assert isValid(preview_ref), f"Cycle {cycle}: preview destroyed during enter!"

        # Exit
        win.toggle_fullscreen_preview()
        assert win._preview_fullscreen is False, f"Cycle {cycle}: state must be normal"
        assert win.centralWidget() is tabs_ref, f"Cycle {cycle}: central must be tabs"
        assert isValid(tabs_ref), f"Cycle {cycle}: tabs destroyed during exit!"
        assert isValid(preview_ref), f"Cycle {cycle}: preview destroyed during exit!"


def test_fullscreen_esc_exit():
    """D. ESC key exits fullscreen safely and idempotently."""
    win = MainWindow()
    ctrl = AppController()
    win.set_controller(ctrl)
    win.show()

    win.enter_fullscreen_preview()
    assert win._preview_fullscreen is True

    # Send ESC event to MainWindow
    esc_event = QKeyEvent(QKeyEvent.KeyPress, Qt.Key_Escape, Qt.NoModifier)
    win.keyPressEvent(esc_event)

    assert win._preview_fullscreen is False
    assert win.centralWidget() is win.tabs
    assert isValid(win.tabs)
    assert isValid(win.preview)


def test_next_frame_advances_integer_domain(capsys):
    """E. NEXT: frame N -> N+1."""
    ctrl = AppController()
    ctrl.fps = 30.0
    ctrl.video_duration_s = 10.0
    ctrl._playback_pos = 1.0  # frame 30
    ctrl._playback_frame = 30

    ctrl._on_frame_step(1)
    out = capsys.readouterr().out
    assert "[FRAME STEP NEXT]" in out
    assert "current_frame=30" in out
    assert "target_frame=31" in out
    assert "actual_frame_after=31" in out
    assert ctrl._playback_frame == 31
    assert abs(ctrl._playback_pos - (31 / 30.0)) < 1e-4


def test_ten_times_next_and_ten_times_prev(capsys):
    """F & G. 10x NEXT (N -> N+10) and 10x PREVIOUS (N+10 -> N)."""
    ctrl = AppController()
    ctrl.fps = 29.97002997002997  # GoPro NTSC
    ctrl.video_duration_s = 60.0
    ctrl._playback_pos = 10.0
    initial_frame = int(round(10.0 * ctrl.fps))
    ctrl._playback_frame = initial_frame

    # 10x NEXT
    for i in range(1, 11):
        ctrl._on_frame_step(1)
        expected_frame = initial_frame + i
        assert ctrl._playback_frame == expected_frame, f"Step +{i}: expected {expected_frame}, got {ctrl._playback_frame}"
        assert abs(ctrl._playback_pos - (expected_frame / ctrl.fps)) < 1e-4

    assert ctrl._playback_frame == initial_frame + 10

    # 10x PREVIOUS
    for i in range(1, 11):
        ctrl._on_frame_step(-1)
        expected_frame = initial_frame + 10 - i
        assert ctrl._playback_frame == expected_frame, f"Step -{i}: expected {expected_frame}, got {ctrl._playback_frame}"
        assert abs(ctrl._playback_pos - (expected_frame / ctrl.fps)) < 1e-4

    # Back to exact initial frame
    assert ctrl._playback_frame == initial_frame


def test_multifile_boundary_next_and_prev(capsys):
    """H. Multi-file boundary crossing with NEXT and PREVIOUS."""
    clip0 = VideoClip(path=Path("Video/GX010114.MP4"), duration_s=10.0, fps=30.0, width=1920, height=1080)
    clip1 = VideoClip(path=Path("Video/GX010115.MP4"), duration_s=10.0, fps=30.0, width=1920, height=1080)
    timeline = VideoTimeline.from_clips([clip0, clip1])

    ctrl = AppController()
    ctrl.fps = 30.0
    ctrl.video_timeline = timeline

    # Set position to last frame of clip 0 (frame 299)
    ctrl._playback_pos = 299 / 30.0
    ctrl._playback_frame = 299

    # NEXT step: must cross into clip 1 at frame 300 (local_time 0.0)
    ctrl._on_frame_step(1)
    out1 = capsys.readouterr().out
    assert "[FRAME STEP NEXT]" in out1
    assert "current_frame=299" in out1
    assert "target_frame=300" in out1
    assert "clip_index=1" in out1
    assert "local_target=0.0000" in out1
    assert ctrl._playback_frame == 300
    assert abs(ctrl._playback_pos - 10.0) < 1e-4

    # PREV step: must cross back into clip 0 at frame 299 (local_time 9.9667)
    ctrl._on_frame_step(-1)
    out2 = capsys.readouterr().out
    assert "[FRAME STEP PREV]" in out2
    assert "current_frame=300" in out2
    assert "target_frame=299" in out2
    assert "clip_index=0" in out2
    assert "local_target=9.9667" in out2
    assert ctrl._playback_frame == 299
    assert abs(ctrl._playback_pos - (299 / 30.0)) < 1e-4
