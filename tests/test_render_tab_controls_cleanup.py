"""Testy jednostkowe i integracyjne dla oczyszczenia kontrolek GUI w zakładkach Projekt i Rendering."""

import os
import sys
import pytest
from PySide6.QtCore import Qt, QPoint
from PySide6.QtWidgets import QApplication, QFileDialog

from src.gui.qt.tabs.project_tab import ProjectTab
from src.gui.qt.tabs.render_tab import RenderTab
from src.gui.qt.widgets.discrete_slider import DiscreteSlider, BitrateControl


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    return app


def test_quality_preset_slider(qapp):
    slider = DiscreteSlider([
        ("Fast", "FAST"),
        ("Balanced", "BALANCED"),
        ("Quality", "QUALITY"),
    ])
    assert slider.count() == 3
    assert slider.currentIndex() == 0
    assert slider.currentText() == "Fast"
    assert slider.currentData() == "FAST"

    slider.setCurrentIndex(1)
    assert slider.currentIndex() == 1
    assert slider.currentText() == "Balanced"
    assert slider.currentData() == "BALANCED"

    slider.setCurrentIndex(2)
    assert slider.currentIndex() == 2
    assert slider.currentText() == "Quality"
    assert slider.currentData() == "QUALITY"

    # Test setting by text and data
    slider.setCurrentText("Fast")
    assert slider.currentIndex() == 0
    assert slider.currentData() == "FAST"

    slider.setCurrentText("QUALITY")
    assert slider.currentIndex() == 2
    assert slider.currentData() == "QUALITY"


def test_resolution_slider(qapp):
    items = ["480p", "720p", "1080p", "4k", "5.3k", "8k", "source"]
    slider = DiscreteSlider(items)
    assert slider.count() == len(items)

    for i, res in enumerate(items):
        slider.setCurrentIndex(i)
        assert slider.currentText() == res
        assert slider.currentData() == res

    slider.setCurrentText("4k")
    assert slider.currentText() == "4k"
    assert slider.currentIndex() == 3


def test_update_rate_slider(qapp):
    items = ["Quarter", "Half", "Full"]
    slider = DiscreteSlider(items)
    assert slider.count() == 3

    slider.setCurrentText("Full")
    assert slider.currentText() == "Full"

    slider.setCurrentText("Half")
    assert slider.currentText() == "Half"

    slider.setCurrentText("Quarter")
    assert slider.currentText() == "Quarter"


def test_hud_resolution_slider(qapp):
    items = ["50%", "75%", "100%", "Auto"]
    slider = DiscreteSlider(items)
    assert slider.count() == 4

    slider.setCurrentText("Auto")
    assert slider.currentText() == "Auto"

    slider.setCurrentText("75%")
    assert slider.currentText() == "75%"


def test_bitrate_control_sync_and_buttons(qapp):
    bc = BitrateControl(min_mbps=5, max_mbps=120, default_mbps=40)
    assert bc.value() == 40
    assert bc.text() == "40M"
    assert bc.display_text() == "40 Mb/s"

    # Step buttons (-1 / +1)
    bc.setValue(10)
    assert bc.value() == 10
    assert bc.text() == "10M"
    assert bc.display_text() == "10 Mb/s"

    bc.btn_left.click()
    assert bc.value() == 9
    assert bc.slider.value() == 9
    assert bc.text() == "9M"
    assert bc.display_text() == "9 Mb/s"

    bc.btn_right.click()
    assert bc.value() == 10
    assert bc.slider.value() == 10
    assert bc.text() == "10M"
    assert bc.display_text() == "10 Mb/s"

    bc.btn_right.click()
    assert bc.value() == 11
    assert bc.slider.value() == 11
    assert bc.text() == "11M"
    assert bc.display_text() == "11 Mb/s"

    # Boundary MIN: 5 + left = 5
    bc.setValue(5)
    bc.btn_left.click()
    assert bc.value() == 5
    assert bc.slider.value() == 5
    assert bc.text() == "5M"
    assert bc.display_text() == "5 Mb/s"

    # Boundary MAX: 120 + right = 120
    bc.setValue(120)
    bc.btn_right.click()
    assert bc.value() == 120
    assert bc.slider.value() == 120
    assert bc.text() == "120M"
    assert bc.display_text() == "120 Mb/s"

    # Slider move
    bc.slider.setValue(25)
    assert bc.value() == 25
    assert bc.text() == "25M"
    assert bc.display_text() == "25 Mb/s"

    # Manual text input
    bc._on_text_edited("10")
    assert bc.value() == 10
    assert bc.slider.value() == 10
    assert bc.text() == "10M"

    bc._on_text_edited("60 Mb/s")
    assert bc.value() == 60
    assert bc.slider.value() == 60
    assert bc.text() == "60M"

    # Clamping
    bc._on_text_edited("1")  # Below min
    assert bc.value() == 5
    assert bc.slider.value() == 5

    bc._on_text_edited("500")  # Above max
    assert bc.value() == 120
    assert bc.slider.value() == 120

    # setText compatibility
    bc.setText("30M")
    assert bc.value() == 30
    assert bc.slider.value() == 30
    assert bc.text() == "30M"
    assert bc.display_text() == "30 Mb/s"


def test_render_tab_controls_integration(qapp):
    rt = RenderTab()
    assert isinstance(rt.cmb_amd_quality, DiscreteSlider)
    assert isinstance(rt.cmb_resolution, DiscreteSlider)
    assert isinstance(rt.cmb_update_rate, DiscreteSlider)
    assert isinstance(rt.cmb_hud_resolution, DiscreteSlider)
    assert isinstance(rt.edit_bitrate, BitrateControl)

    # Restoring quality
    rt.set_amd_encoder_quality("QUALITY")
    assert rt.cmb_amd_quality.currentData() == "QUALITY"
    assert rt.cmb_amd_quality.currentText() == "Quality"

    rt.set_amd_encoder_quality("FAST")
    assert rt.cmb_amd_quality.currentData() == "FAST"
    assert rt.cmb_amd_quality.currentText() == "Fast"

    # Bitrate
    rt.edit_bitrate.setValue(20)
    assert rt.edit_bitrate.text() == "20M"


def test_preview_alignment_project_vs_render(qapp):
    pt = ProjectTab()
    rt = RenderTab()

    # Resize both tabs to typical window size
    test_w, test_h = 1280, 720
    pt.resize(test_w, test_h)
    rt.resize(test_w, test_h)

    pt._update_preview_width()
    rt._update_preview_width()

    # Geometry checks
    assert pt.preview_slot.width() == rt.preview_slot.width()
    assert pt.preview_slot.height() == rt.preview_slot.height()
    assert pt.left_panel.width() == rt.left_panel.width()

    # Margin checks
    assert pt.layout().contentsMargins().left() == 0
    assert rt.layout().contentsMargins().left() == 0
    assert pt.left_panel.layout().contentsMargins().left() == 0
    assert rt.left_panel.layout().contentsMargins().left() == 0


def test_output_dialog_prefill_logic(qapp, monkeypatch):
    rt = RenderTab()
    captured_paths = []

    def mock_get_save_file_name(parent, title, initial_path, filter_str):
        captured_paths.append(initial_path)
        return initial_path, filter_str

    monkeypatch.setattr(QFileDialog, "getSaveFileName", mock_get_save_file_name)

    # 1. Full absolute path
    abs_path = r"C:\Videos\MyRide.mp4"
    rt.edit_output.setText(abs_path)
    rt._select_output()
    assert captured_paths[-1] == abs_path
    assert rt._last_output_dir == r"C:\Videos"

    # 2. Filename only after previous dir was set
    rt.edit_output.setText("NextRide.mp4")
    rt._select_output()
    assert captured_paths[-1] == os.path.join(r"C:\Videos", "NextRide.mp4")
    assert rt._last_output_dir == r"C:\Videos"


def test_amd_encoder_resolution_gate(qapp):
    rt = RenderTab()

    # Switch to CPU: 5.3k and 8k should be enabled
    rt.cmb_encoder.setCurrentText("cpu")
    idx_5k = rt.cmb_resolution.findText("5.3k")
    idx_8k = rt.cmb_resolution.findText("8k")
    assert rt.cmb_resolution.isItemEnabled(idx_5k)
    assert rt.cmb_resolution.isItemEnabled(idx_8k)

    # Select 8k
    rt.cmb_resolution.setCurrentText("8k")
    assert rt.cmb_resolution.currentText() == "8k"

    # Switch to AMD: 5.3k and 8k must be disabled with tooltip, and currentText clamped to 4k
    rt.cmb_encoder.setCurrentText("amd")
    assert not rt.cmb_resolution.isItemEnabled(idx_5k)
    assert not rt.cmb_resolution.isItemEnabled(idx_8k)
    assert "4096" in rt.cmb_resolution._labels[idx_8k].toolTip()
    assert rt.cmb_resolution.currentText() == "4k"

    # Trying to select 8k or 5.3k while AMD is active should clamp back to 4k
    rt.cmb_resolution.setCurrentText("8k")
    assert rt.cmb_resolution.currentText() == "4k"
    rt.cmb_resolution.setCurrentIndex(idx_8k)
    assert rt.cmb_resolution.currentText() == "4k"

    # Switch back to CPU: 5.3k and 8k become enabled again
    rt.cmb_encoder.setCurrentText("cpu")
    assert rt.cmb_resolution.isItemEnabled(idx_5k)
    assert rt.cmb_resolution.isItemEnabled(idx_8k)
    rt.cmb_resolution.setCurrentText("8k")
    assert rt.cmb_resolution.currentText() == "8k"

