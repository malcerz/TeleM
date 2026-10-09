"""Unit and regression tests for explicit default_export_dir setting in Settings -> General,
fallback resolution priorities, and isolation from manual output selection.
"""

import json
import os
from pathlib import Path
import pytest
from PySide6.QtWidgets import QApplication, QFileDialog, QLineEdit, QPushButton

from src.gui.qt.tabs.settings_tab import SettingsTab
from src.gui.qt.tabs.render_tab import RenderTab


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app


def test_default_export_dir_setting_visible_in_general(qapp):
    """1. Setting 'Domyślny folder eksportu' is present in 'Ogólne' with browse/clear buttons and placeholder."""
    tab = SettingsTab()
    assert hasattr(tab, "edit_default_export_dir")
    assert isinstance(tab.edit_default_export_dir, QLineEdit)
    assert hasattr(tab, "btn_export_dir")
    assert isinstance(tab.btn_export_dir, QPushButton)
    assert hasattr(tab, "btn_clear_export_dir")
    assert isinstance(tab.btn_clear_export_dir, QPushButton)

    assert tab.edit_default_export_dir.placeholderText() == "(domyślnie: folder pliku źródłowego)"
    assert tab.btn_export_dir.text() == "Wybierz"
    assert tab.btn_clear_export_dir.text() == "Wyczyść"

    # Test clear button functionality
    tab.edit_default_export_dir.setText("C:/some/custom/path")
    assert tab.edit_default_export_dir.text() == "C:/some/custom/path"
    tab.btn_clear_export_dir.click()
    assert tab.edit_default_export_dir.text() == ""


def test_default_export_dir_persists_after_restart(qapp, tmp_path):
    """2. Setting default_export_dir persists to def_layout.json and restores on simulated restart."""
    def_layout_path = Path(__file__).resolve().parents[1] / "def_layout.json"
    orig_content = def_layout_path.read_text(encoding="utf-8")
    custom_dir = tmp_path / "persistent_export_dir"
    custom_dir.mkdir(parents=True)

    try:
        # A: Set custom export dir and save
        tab1 = SettingsTab()
        tab1.edit_default_export_dir.setText(str(custom_dir))
        tab1._on_save_settings_clicked()

        data_saved = json.loads(def_layout_path.read_text(encoding="utf-8"))
        assert data_saved.get("default_export_dir") == str(custom_dir)
        assert data_saved.get("global", {}).get("default_export_dir") == str(custom_dir)

        # Simulate restart by creating fresh SettingsTab
        tab2 = SettingsTab()
        assert tab2.edit_default_export_dir.text() == str(custom_dir)

        # B: Clear export dir (AUTO mode) and save
        tab2.btn_clear_export_dir.click()
        assert tab2.edit_default_export_dir.text() == ""
        tab2._on_save_settings_clicked()

        data_saved2 = json.loads(def_layout_path.read_text(encoding="utf-8"))
        assert data_saved2.get("default_export_dir") == ""
        assert data_saved2.get("global", {}).get("default_export_dir") == ""

        # Reload in a third instance
        tab3 = SettingsTab()
        assert tab3.edit_default_export_dir.text() == ""

    finally:
        def_layout_path.write_text(orig_content, encoding="utf-8")


def test_default_export_dir_configured_is_used(qapp, tmp_path):
    """3. Configured default_export_dir takes precedence over source video parent folder."""
    tab = RenderTab()
    source_dir = tmp_path / "source_folder"
    source_dir.mkdir(parents=True)
    video_file = source_dir / "ride.mp4"
    video_file.touch()

    configured_dir = tmp_path / "configured_export_dir"
    configured_dir.mkdir(parents=True)

    class DummyCtrl:
        video_paths = [str(video_file)]
        video_path = str(video_file)
        default_export_dir = str(configured_dir)
        layout = {"default_export_dir": str(configured_dir), "global": {"default_export_dir": str(configured_dir)}}

    tab._controller = DummyCtrl()
    resolved = tab.resolve_default_export_dir()
    assert resolved == configured_dir
    assert resolved != source_dir


def test_default_export_dir_empty_uses_source_directory(qapp, tmp_path):
    """4. Empty default_export_dir (AUTO mode) uses the source video parent folder."""
    tab = RenderTab()
    source_dir = tmp_path / "camera_source"
    source_dir.mkdir(parents=True)
    video_file = source_dir / "GH010001.MP4"
    video_file.touch()

    class DummyCtrl:
        video_paths = [str(video_file)]
        video_path = str(video_file)
        default_export_dir = ""
        layout = {"default_export_dir": "", "global": {"default_export_dir": ""}}

    tab._controller = DummyCtrl()
    resolved = tab.resolve_default_export_dir()
    assert resolved == source_dir


def test_invalid_default_export_dir_falls_back_to_source(qapp, tmp_path, capsys):
    """5. Non-existent/unavailable default_export_dir logs warning and falls back to source folder."""
    tab = RenderTab()
    source_dir = tmp_path / "fallback_source"
    source_dir.mkdir(parents=True)
    video_file = source_dir / "DJI_0001.MP4"
    video_file.touch()

    invalid_dir = tmp_path / "unplugged_drive_or_missing_dir"

    class DummyCtrl:
        video_paths = [str(video_file)]
        video_path = str(video_file)
        default_export_dir = str(invalid_dir)
        layout = {"default_export_dir": str(invalid_dir), "global": {"default_export_dir": str(invalid_dir)}}

    tab._controller = DummyCtrl()
    resolved = tab.resolve_default_export_dir()

    captured = capsys.readouterr()
    assert "[EXPORT DIR] configured directory unavailable, using source directory" in captured.out
    assert resolved == source_dir


def test_manual_output_selection_does_not_change_default_export_dir(qapp, tmp_path, monkeypatch):
    """6. Selecting an output file manually in RenderTab does NOT mutate default_export_dir or def_layout.json."""
    tab = RenderTab()
    source_dir = tmp_path / "original_source"
    source_dir.mkdir(parents=True)
    video_file = source_dir / "video.mp4"
    video_file.touch()

    configured_dir = tmp_path / "initial_configured"
    configured_dir.mkdir(parents=True)

    manual_dir = tmp_path / "manual_render_folder"
    manual_dir.mkdir(parents=True)
    chosen_file = manual_dir / "one_off_render.mp4"

    class DummyCtrl:
        video_paths = [str(video_file)]
        video_path = str(video_file)
        default_export_dir = str(configured_dir)
        layout = {"default_export_dir": str(configured_dir), "global": {"default_export_dir": str(configured_dir)}}

    tab._controller = DummyCtrl()

    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *args, **kwargs: (str(chosen_file), "MP4 (*.mp4)"))

    tab._select_output()

    # The edit field receives the user-chosen file
    assert tab.edit_output.text() == str(chosen_file)

    # Controller's default_export_dir MUST NOT be changed
    assert tab._controller.default_export_dir == str(configured_dir)
    assert tab._controller.layout.get("default_export_dir") == str(configured_dir)
    assert tab._controller.layout.get("global", {}).get("default_export_dir") == str(configured_dir)
    # Nor should last_export_dir be added or point to manual_dir
    assert tab._controller.layout.get("global", {}).get("last_export_dir") != str(manual_dir)


def test_queue_job_keeps_resolved_output_snapshot(qapp, tmp_path):
    """7. ExportQueue job takes an immutable snapshot of the resolved output path."""
    tab = RenderTab()
    configured_dir = tmp_path / "export_configured"
    configured_dir.mkdir(parents=True)

    source_dir = tmp_path / "src_videos"
    source_dir.mkdir(parents=True)
    video_file = source_dir / "cam.mp4"
    video_file.touch()

    class DummyCtrl:
        video_paths = [str(video_file)]
        video_path = str(video_file)
        default_export_dir = str(configured_dir)
        layout = {"default_export_dir": str(configured_dir), "global": {"default_export_dir": str(configured_dir)}}
        fit_path = ""
        gpx_path = ""

    tab._controller = DummyCtrl()

    # Initial count (queue may auto-load persisted jobs)
    tab._init_export_queue()
    initial_count = len(tab._export_queue.get_jobs())

    # Set relative filename
    tab.edit_output.setText("rendered_job.mp4")
    tab._on_add_to_queue()

    assert tab._export_queue is not None
    jobs = tab._export_queue.get_jobs()
    assert len(jobs) == initial_count + 1
    job = jobs[-1]
    expected_path = str(configured_dir / "rendered_job.mp4")
    assert job.output_path == expected_path

    # Mutate tab fields and controller default_export_dir
    tab.edit_output.setText("different_job.mp4")
    tab._controller.default_export_dir = str(tmp_path / "another_dir")

    # Queued job remains identical (snapshot invariant)
    assert job.output_path == expected_path


def test_direct_queue_use_same_export_dir_resolver(qapp, tmp_path):
    """8. Both direct render options and queue addition resolve relative paths using resolve_default_export_dir."""
    tab = RenderTab()
    configured_dir = tmp_path / "uniform_exports"
    configured_dir.mkdir(parents=True)

    source_dir = tmp_path / "uniform_src"
    source_dir.mkdir(parents=True)
    video_file = source_dir / "video1.mp4"
    video_file.touch()

    class DummyCtrl:
        video_paths = [str(video_file)]
        video_path = str(video_file)
        default_export_dir = str(configured_dir)
        layout = {"default_export_dir": str(configured_dir), "global": {"default_export_dir": str(configured_dir)}}
        fit_path = ""
        gpx_path = ""

    tab._controller = DummyCtrl()

    # Relative output path
    tab.edit_output.setText("clip.mp4")
    options = tab._build_options_from_gui()
    expected_resolved = str(configured_dir / "clip.mp4")

    # Options built for direct export have resolved path
    assert tab.edit_output.text() == expected_resolved

    # Reset to relative
    tab.edit_output.setText("clip2.mp4")
    tab._on_add_to_queue()
    q_jobs = tab._export_queue.get_jobs()
    assert len(q_jobs) >= 1
    latest_job = q_jobs[-1]
    assert latest_job.output_path == str(configured_dir / "clip2.mp4")


def test_cwd_is_never_default_export_directory(qapp):
    """9. resolve_default_export_dir() NEVER returns current working directory (CWD)."""
    tab = RenderTab()

    # No controller, no video
    tab._controller = None
    resolved_none = tab.resolve_default_export_dir()
    assert resolved_none != Path.cwd()
    assert resolved_none.is_dir()
    assert resolved_none.is_absolute()

    # Controller with empty paths and empty default_export_dir
    class DummyEmptyCtrl:
        video_paths = []
        video_path = None
        default_export_dir = ""
        layout = {}

    tab._controller = DummyEmptyCtrl()
    resolved_empty = tab.resolve_default_export_dir()
    assert resolved_empty != Path.cwd()
    assert resolved_empty.is_dir()
    assert resolved_empty.is_absolute()
