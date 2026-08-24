"""Testy przeciągania wskaźników na podglądzie (drag & drop) i aktualizacji X/Y.

Weryfikują:
1. Kotwiczenie przeciągania — wskaźnik NIE przeskakuje o połowę rozmiaru:
   - forma "text" (i time_display): pozycja (x,y) = lewy-górny róg
   - pozostałe formy (gauge/bar/chart/map): pozycja (x,y) = środek
2. Panel właściwości aktualizuje X/Y po przesunięciu (sig_properties_ready
   → update_field_values).
"""

from __future__ import annotations

import sys
import os

os.environ["QT_QPA_PLATFORM"] = "offscreen"

import pytest

from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QMouseEvent
from PySide6.QtCore import QPointF, Qt, QEvent


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication(sys.argv)
    yield app


class MockController:
    """Minimalny kontroler — tylko layout potrzebny do formy wskaźnika."""

    def __init__(self, layout=None):
        self.layout = layout or {"indicators": {}}


def _make_vp(qapp, layout, bboxes, orig_w=1920, orig_h=1080):
    from src.gui.qt.widgets.video_preview import VideoPreview

    vp = VideoPreview()
    ctrl = MockController(layout)
    vp.set_controller(ctrl)
    vp.image_label.resize(960, 540)  # skala 0.5 względem 1920x1080
    vp.set_bboxes(bboxes, orig_w, orig_h)
    moved: list[tuple[str, float, float]] = []
    clicked: list[str] = []
    vp.signals.sig_indicator_moved.connect(
        lambda k, x, y: moved.append((k, x, y))
    )
    vp.signals.sig_indicator_clicked.connect(clicked.append)
    return vp, moved, clicked


def _press(vp, x, y):
    ev = QMouseEvent(
        QEvent.Type.MouseButtonPress, QPointF(x, y),
        Qt.LeftButton, Qt.LeftButton, Qt.NoModifier,
    )
    return vp.eventFilter(vp.image_label, ev)


def _move(vp, x, y):
    ev = QMouseEvent(
        QEvent.Type.MouseMove, QPointF(x, y),
        Qt.NoButton, Qt.LeftButton, Qt.NoModifier,
    )
    return vp.eventFilter(vp.image_label, ev)


def _release(vp, x, y):
    ev = QMouseEvent(
        QEvent.Type.MouseButtonRelease, QPointF(x, y),
        Qt.LeftButton, Qt.NoButton, Qt.NoModifier,
    )
    return vp.eventFilter(vp.image_label, ev)


# ── Testy kotwiczenia przeciągania ─────────────────────────────────────────


class TestDragAnchor:
    def test_text_anchor_uses_topleft_no_jump(self, qapp):
        """Text: chwytając za środek, pozycja (x,y) = lewy-górny róg — bez przeskoku."""
        # oryginał 1920x1080; wskaźnik text na x=400,y=300, rozmiar 200x80
        layout = {"indicators": {"hr_text": {"form": "text", "x": 20.83, "y": 27.78}}}
        bboxes = {"hr_text": (400, 300, 200, 80)}
        vp, moved, _ = _make_vp(qapp, layout, bboxes)

        # Środek bboxa w oryginale: (500, 340) → w labelu (skala 0.5): (250, 170)
        assert _press(vp, 250, 170) is True
        # Ruch bez puszczenia — najpierw do TEGO SAMEGO punktu (bez przeskoku)
        assert _move(vp, 250, 170) is True

        assert len(moved) == 1
        key, x, y = moved[0]
        assert key == "hr_text"
        # Pozycja layout = lewy-górny róg (400,300) w norm (0..100) — NIE środek
        assert x == pytest.approx(400 / 1920 * 100, abs=0.01)
        assert y == pytest.approx(300 / 1080 * 100, abs=0.01)

        # Ruch o +1px (label) przesuwa o +1px w norm = (1/960*100)
        _move(vp, 251, 171)
        assert len(moved) == 2
        _, x2, y2 = moved[1]
        assert x2 == pytest.approx(x + 1 / 960 * 100, abs=0.01)
        assert y2 == pytest.approx(y + 1 / 540 * 100, abs=0.01)

    def test_gauge_anchor_uses_center_no_jump(self, qapp):
        """Gauge: pozycja (x,y) = środek — chwyt za środek nie zmienia pozycji."""
        layout = {"indicators": {"speed_visual": {"form": "gauge", "x": 31.25, "y": 37.04}}}
        # bbox środkowany na (600,400) w oryginale: x=500,y=300,w=200,h=200
        bboxes = {"speed_visual": (500, 300, 200, 200)}
        vp, moved, _ = _make_vp(qapp, layout, bboxes)

        # Środek bboxa (600,400) → w labelu: (300, 200)
        assert _press(vp, 300, 200) is True
        assert _move(vp, 300, 200) is True

        assert len(moved) == 1
        key, x, y = moved[0]
        assert key == "speed_visual"
        # Pozycja layout = środek (600,400) w norm — bez przeskoku
        assert x == pytest.approx(600 / 1920 * 100, abs=0.01)
        assert y == pytest.approx(400 / 1080 * 100, abs=0.01)

        # Ruch o +1px przesuwa o +1px w norm
        _move(vp, 301, 201)
        assert len(moved) == 2
        _, x2, y2 = moved[1]
        assert x2 == pytest.approx(x + 1 / 960 * 100, abs=0.01)
        assert y2 == pytest.approx(y + 1 / 540 * 100, abs=0.01)

    def test_release_clears_drag(self, qapp):
        """Po puszczeniu przycisku drag jest czyszczony."""
        layout = {"indicators": {"hr_text": {"form": "text", "x": 20.83, "y": 27.78}}}
        bboxes = {"hr_text": (400, 300, 200, 80)}
        vp, moved, _ = _make_vp(qapp, layout, bboxes)

        assert _press(vp, 250, 170) is True
        assert vp._dragging_key == "hr_text"
        _release(vp, 250, 170)
        assert vp._dragging_key is None

    def test_uses_topleft_anchor_forms(self, qapp):
        """_uses_topleft_anchor: text i time_* → True; reszta → False."""
        from src.gui.qt.widgets.video_preview import VideoPreview

        vp = VideoPreview()
        for key in ("time_block", "time_display"):
            assert vp._uses_topleft_anchor(key) is True
        vp._controller = MockController({
            "indicators": {
                "a": {"form": "text"},
                "b": {"form": "gauge"},
                "c": {"form": "bar"},
                "d": {"form": "map"},
                "e": {"form": "chart"},
                "f": {"form": "segment_bar"},
                "g": {},  # brak formy → text (domyślna)
            }
        })
        assert vp._uses_topleft_anchor("a") is True
        assert vp._uses_topleft_anchor("g") is True
        assert vp._uses_topleft_anchor("b") is False
        assert vp._uses_topleft_anchor("c") is False
        assert vp._uses_topleft_anchor("d") is False
        assert vp._uses_topleft_anchor("e") is False
        assert vp._uses_topleft_anchor("f") is False

    def test_hit_test_and_click_emitted(self, qapp):
        """Klik w bbox wskaźnika emituje sig_indicator_clicked."""
        layout = {"indicators": {"hr_text": {"form": "text", "x": 20.83, "y": 27.78}}}
        bboxes = {"hr_text": (400, 300, 200, 80)}
        vp, _, clicked = _make_vp(qapp, layout, bboxes)
        # punkt w środku bboxa w labelu
        assert _press(vp, 250, 170) is True
        assert clicked == ["hr_text"]


# ── Testy aktualizacji X/Y w panelu właściwości ─────────────────────────────


class TestPropertiesXYUpdate:
    def test_xy_update_after_move(self, qapp):
        """Po sig_properties_ready z nowym x/y pole Pozycja X/Y się aktualizuje."""
        from src.gui.qt.widgets.property_editor import PropertyEditor
        from src.gui.qt.models import get_schema_for_form

        editor = PropertyEditor()
        schema = get_schema_for_form("text")
        values = {
            "size": 2.5, "label": "HR", "x": 20.83, "y": 27.78,
            "rotation": "0", "source": "fit", "form": "text",
            "font_size": 1.8, "text_color": "#FFFFFF",
            "text_offset_x": 0.0, "text_offset_y": 0.0,
            "show_units": True, "show_value": True, "unit": "",
            "decimals": 0, "min_val": 0.0, "max_val": 200.0,
        }
        editor.on_properties_ready("hr_text", schema, dict(values))

        # znajdź widgety X/Y
        x_w = editor._field_widgets.get("x")
        y_w = editor._field_widgets.get("y")
        assert x_w is not None and y_w is not None
        assert x_w.value() == pytest.approx(20.83, abs=1e-3)
        assert y_w.value() == pytest.approx(27.78, abs=1e-3)

        # przesunięcie → nowe x/y
        values["x"] = 35.0
        values["y"] = 12.5
        editor.on_properties_ready("hr_text", schema, dict(values))
        assert x_w.value() == pytest.approx(35.0, abs=1e-3)
        assert y_w.value() == pytest.approx(12.5, abs=1e-3)

    def test_xy_spinbox_ranges(self, qapp):
        """Pola X/Y mają zakres 0..100."""
        from src.gui.qt.widgets.property_editor import PropertyEditor
        from src.gui.qt.models import get_schema_for_form

        editor = PropertyEditor()
        schema = get_schema_for_form("text")
        values = {"x": 50.0, "y": 50.0}
        editor.on_properties_ready("hr_text", schema, dict(values))
        assert editor._field_widgets["x"].minimum() == 0.0
        assert editor._field_widgets["x"].maximum() == 100.0
        assert editor._field_widgets["y"].minimum() == 0.0
        assert editor._field_widgets["y"].maximum() == 100.0
