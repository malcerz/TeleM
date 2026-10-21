"""Shared colour field: the swatch opens the picker; Cancel / bad HEX never write."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QColorDialog, QPushButton

from src.gui.qt.models import FieldSchema
from src.gui.qt.signals import get_signals
from src.gui.qt.widgets.property_editor import ColorSwatch, PropertyEditor


@pytest.fixture()
def editor():
    app = QApplication.instance() or QApplication([])
    pe = PropertyEditor()
    schema = [FieldSchema("compass_needle_color", "color", "Kolor wskazówki", tab="Compass", default="#FFD42A")]
    pe.on_properties_ready("compass", schema, {"compass_needle_color": "#ff0000"})
    changes = []
    slot = lambda k, f, v: changes.append((k, f, v))  # noqa: E731
    get_signals().sig_property_changed.connect(slot)
    yield app, pe, changes
    get_signals().sig_property_changed.disconnect(slot)


def _parts(pe):
    row = pe._field_rows["compass_needle_color"]
    return pe._field_widgets["compass_needle_color"], row.findChild(ColorSwatch), row


def test_swatch_click_opens_picker_and_writes_once(editor, monkeypatch):
    app, pe, changes = editor
    edit, swatch, row = _parts(pe)
    assert not [b for b in row.findChildren(QPushButton) if b.text() == "..."]
    seen = []
    monkeypatch.setattr(QColorDialog, "getColor", staticmethod(lambda initial, *a: seen.append(initial.name()) or QColor("#00aa55")))
    QTest.mouseClick(swatch, Qt.LeftButton)
    assert seen == ["#ff0000"]  # opened with the current colour
    assert edit.text() == "#00AA55" and swatch.color_name == "#00AA55"
    assert changes == [("compass", "compass_needle_color", "#00AA55")]


def test_cancel_and_invalid_hex_do_not_write(editor, monkeypatch):
    app, pe, changes = editor
    edit, swatch, _ = _parts(pe)
    monkeypatch.setattr(QColorDialog, "getColor", staticmethod(lambda *a: QColor()))
    QTest.mouseClick(swatch, Qt.LeftButton)
    edit.setText("#12XY9")
    edit.editingFinished.emit()
    assert changes == []
    assert edit.text() == "#ff0000" and swatch.color_name == "#ff0000"
    edit.setText("#123456")
    assert changes == [("compass", "compass_needle_color", "#123456")] and swatch.color_name == "#123456"
