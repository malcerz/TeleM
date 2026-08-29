"""Regression test suite for GUI BAR indicator mouse drag, selection, and position updates.
Lightweight headless tests verifying hit-test, drag math, bbox tracking, and layout sync.
"""

import pytest
import json
import tempfile
import os

from src.gui.qt.widgets.video_preview import VideoPreview
from src.gui.qt.models import get_schema_for_form
from src.indicators.compositor import compose_overlay


class MockController:
    """Minimal controller stub to avoid initializing MPV media player threads during pytest."""
    def __init__(self, layout):
        self.layout = layout

    def _on_indicator_moved(self, key: str, x_norm: float, y_norm: float) -> None:
        if key not in self.layout.get("indicators", {}):
            return
        cfg = self.layout["indicators"][key]
        cfg["x"] = round(x_norm, 2)
        cfg["y"] = round(y_norm, 2)


@pytest.fixture(scope="module")
def qapp():
    from PySide6.QtWidgets import QApplication
    import sys
    app = QApplication.instance() or QApplication(sys.argv)
    return app


def test_bar_bbox_selectable_and_draggable(qapp):
    key = "test_ruler_bar"
    layout = {
        "version": 6,
        "width": 1280,
        "height": 720,
        "global": {"text_outline": 3},
        "indicators": {
            key: {
                "enabled": True, "form": "bar", "bar_style": "ruler",
                "orientation": "horizontal", "x": 50.0, "y": 50.0, "size": 0.4,
            }
        },
        "custom_texts": [],
    }
    
    ctrl = MockController(layout)
    preview = VideoPreview()
    preview.set_controller(ctrl)
    
    bboxes = {}
    compose_overlay(
        1280, 720, ctrl.layout, "fonts/Roboto-Bold.ttf",
        "2024-06-01", "12:00:00",
        50.0, 0.0, 100.0, 0.0, None, None,
        0.0, 0.0, 0.0,
        _bboxes=bboxes,
    )
    
    preview.set_bboxes(dict(bboxes), 1280, 720)
    assert key in bboxes
    bx, by, bw, bh = bboxes[key]
    assert bw > 0 and bh > 0
    
    # 1. Hit-test
    cnx = (bx + bw / 2.0) / 1280.0 * 100.0
    cny = (by + bh / 2.0) / 720.0 * 100.0
    hit = preview._hit_test(cnx, cny)
    assert hit == key
    
    # 2. Mouse Drag update
    ax = (bx + bw / 2.0) / 1280.0 * 100.0
    ay = (by + bh / 2.0) / 720.0 * 100.0
    drag_off = (cnx - ax, cny - ay)
    
    # Move mouse by +10% in X and +15% in Y
    ctrl._on_indicator_moved(key, (cnx + 10.0) - drag_off[0], (cny + 15.0) - drag_off[1])
    
    cfg = ctrl.layout["indicators"][key]
    assert abs(cfg["x"] - 60.0) <= 0.1
    assert abs(cfg["y"] - 65.0) <= 0.1
    
    # 3. Re-render overlay and verify that rendered bbox actually moved
    bboxes2 = {}
    compose_overlay(
        1280, 720, ctrl.layout, "fonts/Roboto-Bold.ttf",
        "2024-06-01", "12:00:00",
        50.0, 0.0, 100.0, 0.0, None, None,
        0.0, 0.0, 0.0,
        _bboxes=bboxes2,
    )
    bx2, by2, bw2, bh2 = bboxes2[key]
    dx = bx2 - bx
    dy = by2 - by
    expected_dx = int(round(10.0 / 100.0 * 1280))
    expected_dy = int(round(15.0 / 100.0 * 720))
    assert abs(dx - expected_dx) <= 2
    assert abs(dy - expected_dy) <= 2


def test_vertical_bar_selectable_and_draggable(qapp):
    key = "alt_ruler_vert"
    layout = {
        "version": 6,
        "width": 1280,
        "height": 720,
        "global": {"text_outline": 3},
        "indicators": {
            key: {
                "enabled": True, "form": "bar", "bar_style": "ruler",
                "orientation": "vertical", "x": 15.0, "y": 50.0, "size": 0.35,
            }
        },
        "custom_texts": [],
    }
    
    ctrl = MockController(layout)
    preview = VideoPreview()
    preview.set_controller(ctrl)
    
    bboxes = {}
    compose_overlay(
        1280, 720, ctrl.layout, "fonts/Roboto-Bold.ttf",
        "2024-06-01", "12:00:00",
        1200.0, 0.0, 2000.0, 0.0, None, None,
        0.0, 0.0, 0.0,
        _bboxes=bboxes,
    )
    
    preview.set_bboxes(dict(bboxes), 1280, 720)
    bx, by, bw, bh = bboxes[key]
    
    cnx = (bx + bw / 2.0) / 1280.0 * 100.0
    cny = (by + bh / 2.0) / 720.0 * 100.0
    hit = preview._hit_test(cnx, cny)
    assert hit == key
    
    # Drag by +5% X, -10% Y
    ctrl._on_indicator_moved(key, cnx + 5.0, cny - 10.0)
    
    cfg = ctrl.layout["indicators"][key]
    assert abs(cfg["x"] - 20.0) <= 0.1
    assert abs(cfg["y"] - 40.0) <= 0.1


def test_missing_telemetry_bar_selectable(qapp):
    key = "missing_slope_bar"
    layout = {
        "version": 6,
        "width": 1280,
        "height": 720,
        "global": {"text_outline": 3},
        "indicators": {
            key: {
                "enabled": True, "form": "bar", "bar_style": "slope",
                "orientation": "vertical", "x": 70.0, "y": 60.0, "size": 0.25,
            }
        },
        "custom_texts": [],
    }
    
    ctrl = MockController(layout)
    preview = VideoPreview()
    preview.set_controller(ctrl)
    
    bboxes = {}
    # Passing None for value to simulate missing telemetry
    compose_overlay(
        1280, 720, ctrl.layout, "fonts/Roboto-Bold.ttf",
        "2024-06-01", "12:00:00",
        0.0, 0.0, 100.0, 0.0, None, None,
        0.0, 0.0, 0.0,
        indicator_values={key: None},
        _bboxes=bboxes,
    )
    
    preview.set_bboxes(dict(bboxes), 1280, 720)
    assert key in bboxes
    bx, by, bw, bh = bboxes[key]
    assert bw > 0 and bh > 0
    
    cnx = (bx + bw / 2.0) / 1280.0 * 100.0
    cny = (by + bh / 2.0) / 720.0 * 100.0
    hit = preview._hit_test(cnx, cny)
    assert hit == key
