"""Unit and regression tests for PropertyEditor QScrollArea.
"""

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QScrollArea
from src.gui.qt.widgets.property_editor import PropertyEditor
from src.gui.qt.models import get_schema_for_indicator


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def test_property_editor_scroll_structure(qapp):
    editor = PropertyEditor()
    assert hasattr(editor, "scroll_area")
    assert isinstance(editor.scroll_area, QScrollArea)
    assert editor.scroll_area.widgetResizable() is True
    assert editor.scroll_area.verticalScrollBarPolicy() == Qt.ScrollBarAsNeeded
    assert editor.scroll_area.horizontalScrollBarPolicy() == Qt.ScrollBarAlwaysOff
    assert editor.scroll_area.widget() is editor.form_container


def test_property_editor_scrollbar_active_on_overflow(qapp):
    editor = PropertyEditor()
    schema = get_schema_for_indicator('fit_garmin_battery_percent_text', 'bar', bar_style='segments')
    values = {'form': 'bar', 'bar_style': 'segments', 'segments': 20, 'min_val': 0.0, 'max_val': 100.0}
    editor.on_properties_ready('fit_garmin_battery_percent_text', schema, values)
    
    # Simulate height constrained to 500px
    editor.resize(420, 500)
    editor.show()
    qapp.processEvents()
    
    vbar = editor.scroll_area.verticalScrollBar()
    assert vbar.maximum() > 0
    assert editor.form_container.height() > 500


def test_property_editor_scroll_to_bottom_reaches_smoothing(qapp):
    editor = PropertyEditor()
    schema = get_schema_for_indicator('fit_garmin_battery_percent_text', 'bar', bar_style='segments')
    values = {'form': 'bar', 'bar_style': 'segments', 'smoothing': 5}
    editor.on_properties_ready('fit_garmin_battery_percent_text', schema, values)
    
    editor.resize(420, 500)
    editor.show()
    qapp.processEvents()
    
    vbar = editor.scroll_area.verticalScrollBar()
    vbar.setValue(vbar.maximum())
    qapp.processEvents()
    
    assert vbar.value() == vbar.maximum()
    assert editor._smoothing_spin.value() == 5


def test_property_editor_dynamic_switch_indicators(qapp):
    editor = PropertyEditor()
    schema1 = get_schema_for_indicator('speed_text', 'gauge')
    editor.on_properties_ready('speed_text', schema1, {'form': 'gauge'})
    editor.resize(420, 500)
    editor.show()
    qapp.processEvents()
    
    assert editor.key_label.text() == "Wskaźnik: speed_text"
    
    schema2 = get_schema_for_indicator('fit_curVpower_text', 'text')
    editor.on_properties_ready('fit_curVpower_text', schema2, {'form': 'text'})
    qapp.processEvents()
    
    assert editor.key_label.text() == "Wskaźnik: fit_curVpower_text"
    assert editor.scroll_area.isVisible() is True
