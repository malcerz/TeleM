"""Unit and integration tests for Preview HUD resize, geometry clamping, and aspect-ratio preservation."""

from __future__ import annotations

import os
import sys
import threading
from unittest.mock import MagicMock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QRect, QSize
from PySide6.QtGui import QImage, QPainter, QPixmap
from PySide6.QtWidgets import QApplication

from src.gui.preview_transform import (
    calculate_displayed_video_rect,
    norm_to_preview_coords,
    preview_to_norm_coords,
    source_to_preview_coords,
)
from src.gui.qt.tabs.render_tab import RenderTab
from src.gui.qt.widgets.video_preview import TopLevelHUDWindow, VideoPreview


def test_video_preview_get_video_rect_letterbox_and_pillarbox():
    app = QApplication.instance() or QApplication(sys.argv)
    preview = VideoPreview()
    preview.show()

    class MockCtrl:
        video_width = 3840
        video_height = 2160
        video_info = {"width": 3840, "height": 2160}

    preview.set_controller(MockCtrl())

    # 1. Exact 16:9 viewport
    preview.stacked_widget.resize(1920, 1080)
    vrect = preview.get_video_rect()
    assert (vrect.x(), vrect.y(), vrect.width(), vrect.height()) == (0, 0, 1920, 1080)

    # 2. Wider viewport (pillarbox) - e.g. 2560x1080 (21:9)
    preview.stacked_widget.resize(2560, 1080)
    vrect = preview.get_video_rect()
    assert vrect.height() == 1080
    assert vrect.width() == 1920
    assert vrect.x() == (2560 - 1920) // 2
    assert vrect.y() == 0

    # 3. Taller viewport (letterbox) - e.g. 1920x1440 (4:3)
    preview.stacked_widget.resize(1920, 1440)
    vrect = preview.get_video_rect()
    assert vrect.width() == 1920
    assert vrect.height() == 1080
    assert vrect.x() == 0
    assert vrect.y() == (1440 - 1080) // 2

    # 4. Reported user viewport: 2678x1458
    preview.stacked_widget.resize(2678, 1458)
    vrect = preview.get_video_rect()
    # 2678 / (16/9) = 1506.375 > 1458, so height-limited (pillarbox):
    # width = 1458 * (16/9) = 2592
    assert vrect.height() == 1458
    assert vrect.width() == 2592
    assert vrect.x() == (2678 - 2592) // 2  # 43
    assert vrect.y() == 0


def test_top_level_hud_window_clamps_to_available_screen_geometry():
    app = QApplication.instance() or QApplication(sys.argv)
    parent = VideoPreview()
    parent.resize(800, 600)
    hud_win = TopLevelHUDWindow(parent)

    hud_win.sync_geometry()
    geom = hud_win.geometry()
    assert geom.width() > 0 and geom.height() > 0

    screen = parent.screen()
    if screen:
        avail = screen.availableGeometry()
        parent.setGeometry(avail.x() + avail.width() - 100, avail.y() + avail.height() - 100, 500, 500)
        hud_win.sync_geometry()
        clamped = hud_win.geometry()
        assert clamped.right() <= avail.right()
        assert clamped.bottom() <= avail.bottom()


def test_top_level_hud_window_paint_event_targets_video_rect():
    app = QApplication.instance() or QApplication(sys.argv)
    preview = VideoPreview()

    class MockCtrl:
        video_width = 3840
        video_height = 2160
        video_info = {"width": 3840, "height": 2160}

    preview.set_controller(MockCtrl())
    preview.stacked_widget.resize(2000, 1000)
    hud_win = TopLevelHUDWindow(preview)

    pixmap = QPixmap(3840, 2160)
    pixmap.fill(0xFFFF0000)
    hud_win.hud_pixmap = pixmap

    target_img = QImage(2000, 1000, QImage.Format_ARGB32_Premultiplied)
    target_img.fill(0x00000000)
    painter = QPainter(target_img)
    vrect = preview.get_video_rect()
    painter.drawPixmap(vrect, hud_win.hud_pixmap)
    painter.end()

    inside_x = vrect.center().x()
    inside_y = vrect.center().y()
    assert (target_img.pixel(inside_x, inside_y) & 0x00FFFFFF) == 0x00FF0000

    if vrect.x() > 0:
        outside_pixel = target_img.pixel(vrect.x() // 2, inside_y)
        assert (outside_pixel >> 24) == 0


def test_render_tab_preview_target_size_uses_video_rect_for_native():
    app = QApplication.instance() or QApplication(sys.argv)
    preview = VideoPreview()

    class MockCtrl:
        video_width = 3840
        video_height = 2160
        video_info = {"width": 3840, "height": 2160}

    ctrl = MockCtrl()
    preview.set_controller(ctrl)
    preview.stacked_widget.resize(2678, 1458)

    tab = RenderTab(preview=preview)
    tab._controller = ctrl
    tab._export_preview_native = True
    tab._rendering = True
    tab._preview_is_foreground = lambda: True
    tab.chk_hud_preview.setChecked(True)

    sizes_called: list[tuple[int, int]] = []
    done_event = threading.Event()

    def mock_build(src_time, tw, th):
        sizes_called.append((tw, th))
        done_event.set()
        return None

    tab._build_preview_qimage = mock_build
    tab._trigger_async_preview(1.0)
    done_event.wait(timeout=2.0)

    dpr = preview.get_dpr()
    expected_w = int(2592 * dpr)
    expected_h = int(1458 * dpr)
    assert len(sizes_called) == 1
    assert sizes_called[0] == (expected_w, expected_h)


def test_gui_resize_and_display_change_does_not_interrupt_export():
    app = QApplication.instance() or QApplication(sys.argv)
    preview = VideoPreview()
    tab = RenderTab(preview=preview)
    tab._rendering = True
    tab._export_preview_native = True

    # Simulate rapid window resize during active export
    for w, h in [(1920, 1080), (1366, 768), (2678, 1458), (800, 600), (3840, 2160)]:
        tab.resize(w, h)
        preview.stacked_widget.resize(w, h)
        app.processEvents()
        # Export must remain active and uninterrupted
        assert tab._rendering is True

    # Simulate minimize and restore
    tab.showMinimized()
    app.processEvents()
    assert tab._rendering is True

    tab.showNormal()
    app.processEvents()
    assert tab._rendering is True


def test_top_level_hud_window_can_show_hud_tab_and_state_contract():
    from PySide6.QtWidgets import QMainWindow, QTabWidget, QWidget, QVBoxLayout
    app = QApplication.instance() or QApplication(sys.argv)
    win = QMainWindow()
    tabs = QTabWidget(win)
    win.tabs = tabs

    # Tab 0: Project tab with preview_slot
    tab0 = QWidget()
    tab0.preview_slot = QWidget(tab0)
    QVBoxLayout(tab0.preview_slot)
    QVBoxLayout(tab0).addWidget(tab0.preview_slot)
    tabs.addTab(tab0, "Projekt")

    # Tab 1: Render tab with preview_slot
    preview = VideoPreview()
    tab0.preview_slot.layout().addWidget(preview)
    render_tab = RenderTab(preview=preview)
    tabs.addTab(render_tab, "Render")

    # Tab 2: Settings tab (no preview_slot)
    tab2 = QWidget()
    tabs.addTab(tab2, "Ustawienia")

    win.show()
    tab0.show()
    tab0.preview_slot.show()
    preview.show()
    if preview.stacked_widget:
        preview.stacked_widget.show()

    hud = TopLevelHUDWindow(preview)
    preview.hud_overlay = hud

    # 1. Project tab active -> HUD allowed
    tabs.setCurrentWidget(tab0)
    assert hud.can_show_hud() is True

    # 2. Settings tab active (no preview_slot) -> HUD strictly forbidden
    tabs.setCurrentWidget(tab2)
    assert hud.can_show_hud() is False

    # 3. Render tab active and exporting -> HUD strictly forbidden (export preview uses hud_preview_label)
    tabs.setCurrentWidget(render_tab)
    preview.setParent(render_tab.preview_slot)
    render_tab.preview_slot.layout().addWidget(preview)
    preview.show()
    if preview.stacked_widget:
        preview.stacked_widget.show()
    render_tab._rendering = True
    assert hud.can_show_hud() is False

    # 4. Render tab idle -> HUD allowed
    render_tab._rendering = False
    assert hud.can_show_hud() is True

    # 5. Minimized main window -> HUD strictly forbidden
    win.showMinimized()
    assert hud.can_show_hud() is False


def test_tab_switching_export_hud_isolation():
    from PySide6.QtWidgets import QMainWindow, QTabWidget, QWidget, QVBoxLayout
    app = QApplication.instance() or QApplication(sys.argv)
    win = QMainWindow()
    tabs = QTabWidget(win)
    win.tabs = tabs

    tab0 = QWidget()
    tab0.preview_slot = QWidget(tab0)
    QVBoxLayout(tab0.preview_slot)
    QVBoxLayout(tab0).addWidget(tab0.preview_slot)
    tabs.addTab(tab0, "Projekt")

    preview = VideoPreview()
    tab0.preview_slot.layout().addWidget(preview)
    render_tab = RenderTab(preview=preview)
    win._render_tab = render_tab
    tabs.addTab(render_tab, "Rendering")

    tab_settings = QWidget()
    tabs.addTab(tab_settings, "Ustawienia")

    tab_wczytaj = QWidget()
    tabs.addTab(tab_wczytaj, "Wczytywanie")

    win.show()
    hud = TopLevelHUDWindow(preview)
    preview.hud_overlay = hud

    # Rendering -> Ustawienia -> Projekt -> Wczytywanie -> Rendering during export
    render_tab._rendering = True

    # 1. Rendering tab
    tabs.setCurrentWidget(render_tab)
    assert hud.can_show_hud() is False

    # 2. Ustawienia tab
    tabs.setCurrentWidget(tab_settings)
    assert hud.can_show_hud() is False

    # 3. Projekt tab during active render
    tabs.setCurrentWidget(tab0)
    assert hud.can_show_hud() is False

    # 4. Wczytywanie tab
    tabs.setCurrentWidget(tab_wczytaj)
    assert hud.can_show_hud() is False

    # 5. Back to Rendering tab
    tabs.setCurrentWidget(render_tab)
    assert hud.can_show_hud() is False

    # 6. Idle after export completes (switch back to Projekt tab where preview is embedded)
    tabs.setCurrentWidget(tab0)
    render_tab._rendering = False
    assert hud.can_show_hud() is True
