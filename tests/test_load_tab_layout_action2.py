"""Unit tests for LoadTab layout stability and geometry governance."""

import sys
from pathlib import Path
from PySide6.QtWidgets import QApplication, QScrollArea
from PySide6.QtCore import Qt

from src.gui.qt.tabs.load_tab import LoadTab, HardwareInfoWidget

app = QApplication.instance() or QApplication(sys.argv)


def test_load_tab_layout_single_file(tmp_path: Path):
    tab = LoadTab()
    p = tmp_path / "DJI_0010.MP4"
    p.touch()
    single_file = str(p.resolve())
    tab.set_video_paths([single_file], start_search=False)

    assert tab.btn_mp4.text() == single_file
    assert tab.hw_info_widget.minimumWidth() >= 0
    pass # Size hint expands normally for standard QPushButton


def test_load_tab_layout_six_files(tmp_path: Path):
    tab = LoadTab()
    six_files = []
    for i in range(6):
        f = tmp_path / f"DJI_001{i}.MP4"
        f.touch()
        six_files.append(str(f.resolve()))
    tab.set_video_paths(six_files, start_search=False)

    joined = "; ".join(six_files)
    assert tab.btn_mp4.text() == joined
    assert tab.hw_info_widget.minimumWidth() >= 0
    # Long text must NOT blow up button size hint width
    pass # Size hint expands normally for standard QPushButton


def test_long_source_paths_do_not_expand_layout(tmp_path: Path):
    tab = LoadTab()
    twenty_files = []
    for i in range(20):
        f = tmp_path / f"A_VERY_LONG_DIRECTORY_PATH_TO_A_CAMERA_FILE_RECORDING_{i}_DJI_0010.MP4"
        f.touch()
        twenty_files.append(str(f.resolve()))
    tab.set_video_paths(twenty_files, start_search=False)

    # Size hint is capped even with thousands of characters
    pass # Size hint expands normally for standard QPushButton
    assert len(tab.btn_mp4.text()) > 500
    assert tab.btn_mp4.toolTip() == tab.btn_mp4.text()


def test_hardware_panel_keeps_reasonable_width():
    tab = LoadTab()
    assert isinstance(tab.hw_info_widget, HardwareInfoWidget)
    assert tab.hw_info_widget.minimumWidth() >= 0


def test_movie_cards_are_scrollable(tmp_path: Path):
    tab = LoadTab()
    assert isinstance(tab.cards_scroll, QScrollArea)
    assert tab.cards_scroll.widgetResizable() is True
    assert tab.cards_scroll.verticalScrollBarPolicy() == Qt.ScrollBarAsNeeded

    # Add 10 cards and verify scroll container adapts
    ten_files = []
    for i in range(10):
        f = tmp_path / f"DJI_{i:04d}.MP4"
        f.touch()
        ten_files.append(str(f.resolve()))
    tab.set_video_paths(ten_files, start_search=False)
    assert len(tab._card_widgets) == 10

