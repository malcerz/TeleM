"""Targeted contracts for the preview shown while export is running."""

from __future__ import annotations

import os
import sys
from unittest.mock import MagicMock

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PIL import Image
from PySide6.QtGui import QColor, QImage, QPixmap
from PySide6.QtWidgets import QApplication

from src.gui.export_preview import compose_export_preview
from src.gui.qt.tabs.render_tab import (
    EXPORT_PREVIEW_DIM_ALPHA,
    RenderTab,
    dim_export_preview_qimage,
)
from src.gui.qt.widgets.video_preview import VideoPreview
from src.render_progress import RenderProgressState


def test_export_preview_dims_video_but_keeps_hud_normal_and_preserves_input():
    video = Image.new("RGBA", (4, 2), (200, 100, 50, 123))
    hud = Image.new("RGBA", (4, 2), (0, 0, 0, 0))
    hud.putpixel((0, 0), (250, 240, 230, 255))
    before = video.copy()

    result = compose_export_preview(video, hud, brightness=0.55)

    assert result.getpixel((1, 1)) == (110, 55, 27, 123)
    assert result.getpixel((0, 0)) == (250, 240, 230, 255)
    assert video.tobytes() == before.tobytes()


def test_qimage_dimming_is_owned_by_active_export_preview_only():
    source = QImage(2, 1, QImage.Format_ARGB32)
    source.fill(QColor(200, 100, 50, 255))
    before = source.copy()

    edit_copy = dim_export_preview_qimage(source, render_active=False)
    export_copy = dim_export_preview_qimage(source, render_active=True)

    assert edit_copy.pixelColor(0, 0) == before.pixelColor(0, 0)
    assert export_copy.pixelColor(0, 0).getRgb() == (181, 91, 45, 255)
    assert source.pixelColor(0, 0) == before.pixelColor(0, 0)
    assert EXPORT_PREVIEW_DIM_ALPHA == 24
    assert EXPORT_PREVIEW_DIM_ALPHA / 255.0 == pytest.approx(0.0941176471)


def test_export_preview_native_route_updates_existing_hud_overlay():
    app = QApplication.instance() or QApplication(sys.argv)
    preview = VideoPreview()

    class Controller:
        mpv_player = object()
        _preview_mode = "hud"

    controller = Controller()
    preview._controller = controller
    tab = RenderTab(preview=preview)
    tab._controller = controller
    tab._rendering = True
    tab._export_preview_native = True

    qimg = QImage(8, 4, QImage.Format_RGBA8888)
    qimg.fill(0xFFFFFFFF)
    tab._on_export_preview_ready(qimg)
    app.processEvents()

    assert preview.hud_overlay.hud_pixmap is not None
    assert not preview.hud_overlay.hud_pixmap.isNull()


def test_export_progress_preview_throttle_remains_latest_state_1hz():
    app = QApplication.instance() or QApplication(sys.argv)
    tab = RenderTab(preview=VideoPreview())
    tab._rendering = True
    tab.chk_hud_preview.setChecked(True)
    calls: list[float] = []
    tab._trigger_async_preview = calls.append

    tab._on_render_progress(1, 100, 0.1, 10.0, {"ts": 1.0})
    tab._on_render_progress(2, 100, 0.2, 10.0, {"ts": 2.0})
    assert calls == [1.0]

    tab._last_preview_time -= tab._EXPORT_PREVIEW_INTERVAL_S
    tab._on_render_progress(3, 100, 0.3, 10.0, {"ts": 3.0})
    assert calls == [1.0, 3.0]
    app.processEvents()


def test_export_preview_native_video_tracks_hud_timestamp():
    app = QApplication.instance() or QApplication(sys.argv)
    preview = VideoPreview()

    class Controller:
        mpv_player = MagicMock()

        @staticmethod
        def _resolve_preview_time(global_ts):
            return {"local_time": global_ts, "clip_index": 0, "clip": object()}

        @staticmethod
        def _preview_ensure_active_clip(*_args):
            return False

    controller = Controller()
    tab = RenderTab(preview=preview)
    tab._controller = controller
    tab._rendering = True
    tab._export_preview_native = True

    tab._sync_export_video_to_timestamp(12.5)

    controller.mpv_player.seek.assert_called_once_with(
        12.5, reference="absolute"
    )
    assert controller.mpv_player.pause is True
    app.processEvents()


@pytest.mark.parametrize("terminal_flag", ["completed", "failed", "cancelled"])
def test_terminal_render_state_restores_undimmed_edit_preview(monkeypatch, terminal_flag):
    app = QApplication.instance() or QApplication(sys.argv)
    preview = VideoPreview()
    tab = RenderTab(preview=preview)
    tab._render_generation_id = 77
    tab._render_state_enabled = True
    tab._rendering = True
    tab.preview_slot.setVisible(False)
    tab.hud_preview_label.setVisible(True)
    image = QImage(2, 1, QImage.Format_ARGB32)
    image.fill(QColor(120, 90, 60, 255))
    tab.hud_preview_label.setPixmap(QPixmap.fromImage(image))
    monkeypatch.setattr(tab, "_stop_export_preview", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(tab, "_log_export_preview_resources", lambda: None)

    flags = {"completed": False, "failed": False, "cancelled": False}
    flags[terminal_flag] = True
    tab._on_render_state(RenderProgressState(
        generation_id=77,
        state=terminal_flag,
        **flags,
    ))
    app.processEvents()

    assert tab._rendering is False
    assert tab.hud_preview_label.isHidden()
    pixmap = tab.hud_preview_label.pixmap()
    assert pixmap is None or pixmap.isNull()
    assert not tab.preview_slot.isHidden()
    assert preview.hud_overlay.hud_pixmap is None
