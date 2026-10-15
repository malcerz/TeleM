"""Unit and regression tests for explicit default_export_dir setting in Settings -> General,
fallback resolution priorities, and isolation from manual output selection.
"""

import hashlib
import json
import os
from pathlib import Path
import pytest
from PySide6.QtWidgets import QApplication, QFileDialog, QLineEdit, QPushButton, QMessageBox

from src.gui.qt.tabs.settings_tab import SettingsTab
from src.gui.qt.tabs.render_tab import RenderTab


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app


@pytest.fixture(autouse=True)
def isolated_appdata(monkeypatch, tmp_path):
    """Keep preference and queue persistence out of the user's real profile."""
    monkeypatch.setenv("APPDATA", str(tmp_path / "roaming"))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))


def test_default_export_dir_setting_visible_in_general(qapp, tmp_path, monkeypatch):
    """1. Setting 'Domyślny folder eksportu' is present in 'Ogólne' with browse/clear buttons and placeholder."""
    tab = SettingsTab()
    assert hasattr(tab, "edit_default_export_dir")
    assert isinstance(tab.edit_default_export_dir, QLineEdit)
    assert hasattr(tab, "btn_export_dir")
    assert isinstance(tab.btn_export_dir, QPushButton)
    assert hasattr(tab, "btn_clear_export_dir")
    assert isinstance(tab.btn_clear_export_dir, QPushButton)

    assert tab.edit_default_export_dir.placeholderText() == "Domyślnie: katalog filmu źródłowego."
    assert tab.btn_export_dir.text() == "Wybierz"
    assert tab.btn_clear_export_dir.text() == "Wyczyść"

    chosen_dir = tmp_path / "Żółć i gęślą jaźń"
    chosen_dir.mkdir()
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", lambda *args, **kwargs: str(chosen_dir))
    tab.btn_export_dir.click()
    assert tab.edit_default_export_dir.text() == str(chosen_dir)

    # Clear only empties the form; the green "Zapisz ustawienia" persists
    # automatic source-folder mode (its export-dir step is called directly
    # here so no layout save runs).
    tab.btn_clear_export_dir.click()
    assert tab.edit_default_export_dir.text() == ""
    from src.export_paths import load_default_export_dir
    assert load_default_export_dir() is None
    assert tab._save_default_export_dir(show_message=False) is True
    assert load_default_export_dir() == ""


def test_default_export_dir_persists_after_restart(qapp, tmp_path, monkeypatch):
    """2. Setting default_export_dir persists in the user profile, not in the layout."""
    def_layout_path = Path(__file__).resolve().parents[1] / "def_layout.json"
    orig_hash = hashlib.sha256(def_layout_path.read_bytes()).hexdigest()
    custom_dir = tmp_path / "persistent_export_dir"
    custom_dir.mkdir(parents=True)
    monkeypatch.setattr(QMessageBox, "information", lambda *args, **kwargs: QMessageBox.Ok)
    monkeypatch.setattr(QMessageBox, "warning", lambda *args, **kwargs: QMessageBox.Ok)

    tab1 = SettingsTab()
    tab1.edit_default_export_dir.setText(str(custom_dir))
    tab1._save_default_export_dir()

    pref_path = Path(os.environ["APPDATA"]) / "SportCamHUD" / "app_preferences.json"
    data_saved = json.loads(pref_path.read_text(encoding="utf-8"))
    assert data_saved["default_export_dir"] == str(custom_dir)
    assert SettingsTab().edit_default_export_dir.text() == str(custom_dir)

    tab2 = SettingsTab()
    tab2.btn_clear_export_dir.click()
    tab2._save_default_export_dir()
    assert json.loads(pref_path.read_text(encoding="utf-8"))["default_export_dir"] == ""
    assert SettingsTab().edit_default_export_dir.text() == ""
    assert hashlib.sha256(def_layout_path.read_bytes()).hexdigest() == orig_hash


def test_default_export_dir_configured_is_used(qapp, tmp_path):
    """3. Configured default_export_dir takes precedence over source video parent folder."""
    tab = RenderTab()
    source_dir = tmp_path / "source_folder"
    source_dir.mkdir(parents=True)
    video_file = source_dir / "ride.mp4"
    video_file.touch()

    configured_dir = tmp_path / "configured_export_dir"
    configured_dir.mkdir(parents=True)

    from src.export_paths import save_default_export_dir
    save_default_export_dir(str(configured_dir))

    class DummyCtrl:
        video_paths = [str(video_file)]
        video_path = str(video_file)
        default_export_dir = ""
        layout = {}

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


def test_invalid_default_export_dir_falls_back_to_source(qapp, tmp_path, capsys, monkeypatch):
    """5. Non-existent/unavailable default_export_dir logs warning and falls back to source folder."""
    tab = RenderTab()
    monkeypatch.setattr(QMessageBox, "warning", lambda *args, **kwargs: QMessageBox.Ok)
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
    assert tab._resolve_gui_export_path(str(chosen_file)) == chosen_file


def test_multiclip_uses_first_mp4_parent(qapp, tmp_path, monkeypatch):
    from src.export_paths import save_default_export_dir

    save_default_export_dir("")
    first_dir = tmp_path / "clip_one"
    second_dir = tmp_path / "clip_two"
    first_dir.mkdir()
    second_dir.mkdir()
    first_video = first_dir / "one.mp4"
    second_video = second_dir / "two.mp4"
    first_video.touch()
    second_video.touch()

    class DummyCtrl:
        video_paths = [str(first_video), str(second_video)]
        video_path = str(first_video)
        layout = {}

    tab = RenderTab()
    tab._controller = DummyCtrl()
    assert tab.resolve_default_export_dir() == first_dir


def test_unc_destination_is_deferred_without_gui_probe(qapp, tmp_path):
    from src.export_paths import resolve_export_path

    source_dir = tmp_path / "source"
    source_dir.mkdir()
    source_video = source_dir / "ride.mp4"
    source_video.touch()
    resolved = resolve_export_path(
        "ride_export.mp4",
        source_paths=[source_video],
        configured_dir=r"\\offline-server\share\exports",
        defer_remote_validation=True,
    )
    assert str(resolved).startswith(r"\\offline-server\share\exports")


def test_unwritable_default_falls_back_to_source(qapp, tmp_path, monkeypatch, capsys):
    import src.export_paths as export_paths

    source_dir = tmp_path / "source_writable"
    source_dir.mkdir()
    source_video = source_dir / "ride.mp4"
    source_video.touch()
    blocked_dir = tmp_path / "configured_but_unwritable"
    blocked_dir.mkdir()
    real_check = export_paths.is_export_dir_usable

    def check(path):
        return Path(path) != blocked_dir and real_check(path)

    monkeypatch.setattr(export_paths, "is_export_dir_usable", check)
    resolved = export_paths.resolve_export_path(
        "render.mp4",
        source_paths=[source_video],
        configured_dir=blocked_dir,
    )
    assert resolved == source_dir / "render.mp4"
    assert "configured directory unavailable" in capsys.readouterr().out


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
    assert job.options["_resolved_output_path"] == expected_path

    # Mutate tab fields and controller default_export_dir
    tab.edit_output.setText("different_job.mp4")
    tab._controller.default_export_dir = str(tmp_path / "another_dir")

    # Queued job remains identical (snapshot invariant)
    assert job.output_path == expected_path
    assert job.options["_resolved_output_path"] == expected_path
    from src.export_paths import save_default_export_dir
    save_default_export_dir(str(tmp_path / "new_global_destination"))

    from src.gui.qt._mixins.render_mixin import RenderMixin

    class DummyQueuedRenderer(RenderMixin):
        video_paths = [str(video_file)]
        video_path = str(video_file)
        layout = job.layout

    # Execution sees the job's frozen absolute output, regardless of the new preference.
    assert DummyQueuedRenderer()._resolve_render_output_path(job.output_path) == Path(expected_path)


def test_queue_rejects_relative_and_missing_output_without_creating_directories(tmp_path):
    from src.gui.export_queue import ExportJob, validate_job_snapshot

    source_video = tmp_path / "source.mp4"
    source_video.touch()
    missing_dir = tmp_path / "must_not_be_created"
    job = ExportJob(
        video_paths=[str(source_video)],
        layout={"global": {"font": "Arial"}},
        output_path=str(missing_dir / "render.mp4"),
    )
    valid, message = validate_job_snapshot(job)
    assert not valid
    assert "nie istnieje" in message
    assert not missing_dir.exists()

    job.output_path = "render.mp4"
    valid, message = validate_job_snapshot(job)
    assert not valid
    assert "Nierozstrzygnięta" in message


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

    # The direct render mixin and queue use the same central resolution policy.
    from src.gui.qt._mixins.render_mixin import RenderMixin

    class DummyRenderer(RenderMixin):
        video_paths = [str(video_file)]
        video_path = str(video_file)
        layout = DummyCtrl.layout

    assert str(DummyRenderer()._resolve_render_output_path("clip.mp4")) == expected_resolved
    assert str(tab._resolve_gui_export_path("clip.mp4")) == expected_resolved
    assert options["output"] == "clip.mp4"

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

    # No controller, no video: fail clearly rather than using CWD or a guessed path.
    tab._controller = None
    with pytest.raises(RuntimeError, match="Brak dostępnego katalogu eksportu"):
        tab.resolve_default_export_dir()

    # Controller with empty paths and empty default_export_dir
    class DummyEmptyCtrl:
        video_paths = []
        video_path = None
        default_export_dir = ""
        layout = {}

    tab._controller = DummyEmptyCtrl()
    with pytest.raises(RuntimeError, match="Brak dostępnego katalogu eksportu"):
        tab.resolve_default_export_dir()
