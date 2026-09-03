"""Unit tests for the graphical IconPickerWidget and its PropertyEditor integration."""

import os
import pytest
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt

# Ensure QApplication exists for headless test execution
@pytest.fixture(scope="session")
def qapp():
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def test_icon_picker_initialization_and_selection(qapp):
    from src.gui.qt.widgets.icon_picker import IconPickerWidget

    picker = IconPickerWidget(current_value="heart_pulse")
    assert picker.get_value() == "heart_pulse"
    assert "heart_pulse" in picker.lbl_selected_name.text()

    # Test signal emission
    received = []
    picker.icon_changed.connect(lambda k: received.append(k))

    # Select another icon
    picker._select_icon("speedometer")
    assert picker.get_value() == "speedometer"
    assert received == ["speedometer"]
    assert "speedometer" in picker.lbl_selected_name.text()

    # Clear to none
    picker.btn_none.click()
    assert picker.get_value() == "none"
    assert received[-1] == "none"
    assert "Brak" in picker.lbl_selected_name.text()


def test_icon_picker_search_filtering(qapp):
    from src.gui.qt.widgets.icon_picker import IconPickerWidget

    picker = IconPickerWidget(current_value="clock")
    # All buttons visible initially (not hidden)
    visible_initial = sum(1 for b in picker._buttons.values() if not b.isHidden())
    assert visible_initial > 60

    # Search for 'gopro'
    picker.search_input.setText("gopro")
    assert not picker._buttons["gopro"].isHidden()
    assert picker._buttons["clock"].isHidden()

    # Clear search
    picker.search_input.setText("")
    assert not picker._buttons["clock"].isHidden()


def test_property_editor_integrates_icon_picker(qapp):
    from src.gui.qt.widgets.property_editor import PropertyEditor
    from src.gui.qt.widgets.icon_picker import IconPickerWidget
    from src.gui.qt.models import FieldSchema

    editor = PropertyEditor()
    schema = [
        FieldSchema("size", "float", "Rozmiar", tab="", default=1.0),
        FieldSchema("icon", "choice", "Ikona", tab="Ikona", default="clock"),
    ]
    values = {"size": 1.0, "icon": "heart"}

    editor.on_properties_ready("test_indicator", schema, values)

    # Check that icon widget in editor is IconPickerWidget
    icon_w = editor._field_widgets.get("icon")
    assert isinstance(icon_w, IconPickerWidget)
    assert icon_w.get_value() == "heart"

    # Test update_field_values
    editor.update_field_values({"icon": "rocket"})
    assert icon_w.get_value() == "rocket"
