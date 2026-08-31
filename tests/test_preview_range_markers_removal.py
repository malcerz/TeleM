"""Preview timeline contract: range selection belongs to Export, not preview."""

from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QPushButton

from src.gui.qt.widgets.seek_bar import SeekBar
from src.gui.qt.widgets.video_preview import VideoPreview
from src.gui.qt.tabs.render_tab import RenderTab


def _qapp() -> QApplication:
    return QApplication.instance() or QApplication(sys.argv)


def test_seekbar_renders_only_track_and_playhead() -> None:
    app = _qapp()
    bar = SeekBar()
    bar.resize(240, 26)
    bar.set_duration(100.0)
    # Internal APIs remain available, but must not create preview artwork.
    bar.set_range(20.0, 80.0)
    bar.set_cut_regions([(10.0, 20.0)])
    bar.set_position(50.0)
    bar.show()
    app.processEvents()

    image = bar.grab().toImage()
    # The former orange/red/yellow range artwork is absent. The light-blue
    # playhead is intentionally not part of these forbidden color families.
    forbidden = 0
    for y in range(image.height()):
        for x in range(image.width()):
            c = image.pixelColor(x, y)
            if c.alpha() > 0 and (
                (c.red() > 170 and c.green() < 150 and c.blue() < 140)
                or (c.red() > 190 and c.green() > 130 and c.blue() < 130)
            ):
                forbidden += 1
    assert forbidden == 0


def test_seekbar_endpoint_click_is_still_scrub() -> None:
    _qapp()
    bar = SeekBar()
    bar.resize(240, 26)
    bar.set_duration(100.0)
    positions: list[float] = []
    bar.sig_position_changed.connect(positions.append)
    bar.show()
    QTest.mouseClick(bar, Qt.LeftButton, pos=QPoint(4, 6))
    assert positions
    assert bar._dragging is None


def test_video_preview_has_no_cut_controls_and_export_has_own_controls() -> None:
    _qapp()
    preview = VideoPreview()
    assert not hasattr(preview, "cut_btn")
    assert not hasattr(preview, "undo_cut_btn")
    assert not hasattr(preview, "restore_cut_btn")

    export = RenderTab(preview=preview)
    assert export.btn_in.text() == "IN"
    assert export.btn_out.text() == "OUT"
    assert export.btn_clear_range.isEnabled()
    assert any(button.text() == "IN" for button in export.findChildren(QPushButton))


def test_export_cut_state_does_not_change_preview_axis() -> None:
    _qapp()

    class Controller:
        _cut_regions = [(10.0, 20.0)]

    preview = VideoPreview()
    preview.set_controller(Controller())
    preview.on_duration_ready(100.0)
    preview._on_cut_region_changed()

    assert preview.seek_bar.get_effective_duration() == 100.0
    assert preview.seek_bar.orig_to_eff(50.0) == 50.0


def test_preview_render_has_no_cut_region_overlay() -> None:
    source = Path("src/gui/qt/_mixins/preview_mixin.py").read_text(encoding="utf-8")
    assert "WYCIĘTY FRAGMENT" not in source
    assert "is_in_cut_region(global_time)" not in source
