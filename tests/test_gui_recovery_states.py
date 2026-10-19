"""Real Qt widgets and signals; no video export or private preferences writes."""
import json
import os
from pathlib import Path
import threading
from types import SimpleNamespace

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtCore import Qt, QTimer
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import QApplication, QMessageBox


@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def isolated(monkeypatch, tmp_path, qapp):
    import src.gui.qt.signals as signals
    import src.gui.qt.tabs.settings_tab as settings
    monkeypatch.setattr(signals, "_signals", signals.AppSignals())
    monkeypatch.setenv("APPDATA", str(tmp_path / "roaming"))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    monkeypatch.setattr(settings, "__file__", str(tmp_path / "app/src/gui/qt/tabs/settings_tab.py"))
    for name in ("critical", "warning", "information"):
        monkeypatch.setattr(QMessageBox, name, lambda *a, **k: QMessageBox.Ok)
    yield
    qapp.closeAllWindows()
    qapp.processEvents()


def window():
    from src.gui.qt.main_window import MainWindow
    win = MainWindow()
    win.show()
    return win


def enabled_tabs(win):
    return [win.tabs.isTabEnabled(i) for i in range(win.tabs.count())]


def test_tabs_wait_for_committed_project_and_ignore_generic_progress(qapp):
    win = window()
    assert enabled_tabs(win) == [True, False, True, True]
    assert win.tabs.currentWidget() is win._load_tab
    s = win.signals
    s.sig_project_load_state.emit(dict(generation=1, state="loading", ready=False))
    s.sig_progress.emit(100, "Metadane gotowe")
    s.sig_data_streams_ready.emit([])
    assert enabled_tabs(win) == [True, False, True, True]
    assert win._load_tab._loading
    s.sig_project_load_state.emit(dict(generation=1, state="ready", ready=True))
    assert enabled_tabs(win) == [True, True, True, True]
    assert win.tabs.currentWidget() is win._project_tab
    assert win._load_tab.btn_load.isEnabled()
    s.sig_project_load_state.emit(dict(generation=2, state="loading", ready=False))
    s.sig_project_load_state.emit(dict(generation=1, state="ready", ready=True))
    assert enabled_tabs(win) == [True, False, True, True]
    s.sig_project_load_state.emit(dict(generation=2, state="failed", ready=False))
    assert enabled_tabs(win) == [True, False, True, True]
    assert win._load_tab.btn_load.isEnabled()


def test_worker_signal_is_queued_and_clear_relocks(qapp):
    win = window()
    def complete():
        win.signals.sig_project_load_state.emit(dict(generation=1, state="ready", ready=True))
    worker = threading.Thread(target=complete)
    worker.start(); worker.join()
    assert not win.tabs.isTabEnabled(1)
    qapp.processEvents()
    assert win.tabs.isTabEnabled(1)
    QTest.mouseClick(win._load_tab.btn_clear, Qt.LeftButton) if hasattr(win._load_tab, "btn_clear") else win._load_tab._on_clear()
    assert enabled_tabs(win) == [True, False, True, True]


def test_failed_candidate_keeps_previous_valid_project_and_clear_cancels_pending(monkeypatch, tmp_path, qapp):
    import src.gui.qt._mixins.project_mixin as module
    from src.gui.qt._mixins.project_mixin import ProjectMixin
    win = window()
    jobs = []
    class DeferredThread:
        def __init__(self, target, **kwargs): self.target = target
        def start(self): jobs.append(self.target)
    class Owner(ProjectMixin):
        pass
    owner = Owner()
    owner.signals = win.signals
    owner.video_paths = [Path("previous.mp4")]
    owner.video_path = owner.video_paths[0]
    owner.project_ready = True
    owner._project_load_generation = 0
    owner.base_dir = tmp_path
    owner.ffprobe_path = "ffprobe"
    owner._project_video_time_range = lambda *a, **k: (None, None)
    owner._probe_candidate_video_state = lambda *a, **k: (_ for _ in ()).throw(ValueError("invalid video"))
    owner._on_playback_stop = lambda: None
    owner.is_using_mpv = lambda: False
    owner.telemetry = SimpleNamespace(clear_all=lambda: None)
    owner._clear_caches = lambda: None
    win._controller = owner
    # MainWindow normally reports this modal error; it is expected here.
    monkeypatch.setattr(module, "find_executable", lambda *a, **k: "tool")
    monkeypatch.setattr(module.threading, "Thread", DeferredThread)
    owner._on_files_selected(["invalid.mp4"], "", "")
    assert not win.tabs.isTabEnabled(1)
    jobs.pop()()
    assert owner.project_ready and win.tabs.isTabEnabled(1)
    assert owner.video_paths == [Path("previous.mp4")]
    owner._on_files_selected(["later.mp4"], "", "")
    old_generation = owner._project_load_generation
    owner.clear_project()
    jobs.pop()()
    owner._publish_project_load_state("ready", old_generation)
    assert not owner.project_ready and not owner.video_paths
    assert enabled_tabs(win) == [True, False, True, True]
    owner._on_playback_stop = lambda: (_ for _ in ()).throw(RuntimeError("preview stopped"))
    owner.clear_project()
    assert not owner.video_paths and not win.tabs.isTabEnabled(1)


def test_window_close_cancels_pending_project_loading():
    win = window()
    cancel = threading.Event()
    win._controller = SimpleNamespace(_load_cancel_event=cancel)
    win.close()
    assert cancel.is_set()


def test_settings_restore_is_silent_and_user_change_is_not(tmp_path):
    from src.gui.qt.tabs.settings_tab import SettingsTab
    tab = SettingsTab()
    tab.base_dir.mkdir(parents=True)
    (tab.base_dir / "def_layout.json").write_text(json.dumps({"integrations": {"auto_activity_source": "strava"}}))
    spy = QSignalSpy(tab.signals.sig_settings_changed)
    tab._load_integration_settings()
    assert spy.count() == 0
    assert tab.cmb_auto_source.currentData() == "strava"
    assert not tab.strava_container.isHidden() and tab.garmin_container.isHidden()
    tab.cmb_auto_source.setCurrentIndex(0)
    assert tab.cmb_auto_source.currentText() == "--"
    assert spy.count() == 1 and spy.at(0) == ["auto_activity_source", "none"]


def test_settings_has_left_controls_and_right_white_license_panel(qapp):
    from src.gui.qt.tabs.settings_tab import SettingsTab
    from PySide6.QtGui import QColor, QPalette
    tab = SettingsTab()
    tab.resize(1500, 950)
    tab.show()
    qapp.processEvents()
    assert tab.settings_splitter.widget(0) is tab.settings_scroll
    assert tab.settings_splitter.widget(1) is tab.licenses_panel
    assert tab.settings_scroll.geometry().right() < tab.licenses_panel.geometry().left()
    assert tab.settings_content.isAncestorOf(tab.cmb_font)
    assert tab.licenses_panel.text.isReadOnly()
    assert tab.licenses_panel.text.palette().color(QPalette.Base) == QColor("white")


@pytest.mark.parametrize("provider", ["garmin", "strava", "strava_oauth"])
def test_connection_exception_restores_buttons(provider, monkeypatch, qapp):
    from src.gui.qt.tabs.settings_tab import SettingsTab
    tab = SettingsTab()
    def fail(*args, **kwargs):
        raise RuntimeError("TEST_PROVIDER_FAILURE")
    if provider == "garmin":
        import src.integrations.garmin_connect as module
        monkeypatch.setattr(module, "GarminProvider", fail)
        tab._on_garmin_test_clicked()
        buttons = [tab.btn_garmin_connect, tab.btn_garmin_test, tab.btn_garmin_disconnect]
        label = tab.lbl_garmin_status
    elif provider == "strava":
        import src.integrations.strava as module
        monkeypatch.setattr(module, "StravaProvider", fail)
        tab._on_strava_test_clicked()
        buttons = [tab.btn_strava_connect, tab.btn_strava_test]
        label = tab.lbl_strava_status
    else:
        import src.integrations.strava as module
        monkeypatch.setattr(module, "run_strava_oauth_flow", fail)
        tab.edit_strava_client_secret.setText("fixture")
        tab._on_strava_connect_clicked()
        buttons = [tab.btn_strava_connect, tab.btn_strava_test]
        label = tab.lbl_strava_status
    for _ in range(100):
        QTest.qWait(10)
        if "TEST_PROVIDER_FAILURE" in label.text(): break
    assert "TEST_PROVIDER_FAILURE" in label.text()
    assert all(button.isEnabled() for button in buttons)


@pytest.mark.parametrize("terminal", ["completed", "cancelled", "failed"])
def test_render_controls_restore_after_each_terminal(terminal, tmp_path):
    from src.gui.qt.tabs.render_tab import RenderTab
    from src.render_progress import RenderProgressState
    tab = RenderTab()
    tab.show()
    assert tab.btn_render.isEnabled() and not tab.btn_cancel.isEnabled()
    assert tab._start_render({"output": str(tmp_path / "out.mp4"), "encoder": "cpu"})
    assert not tab.btn_render.isEnabled() and tab.btn_cancel.isEnabled()
    generation = tab._render_generation_id
    tab._on_render_state(RenderProgressState(generation_id=generation, state="cancelling", cancel_requested=True))
    assert not tab.btn_render.isEnabled()
    tab._on_render_state(RenderProgressState(generation_id=generation, state=terminal,
        completed=terminal=="completed", cancelled=terminal=="cancelled", failed=terminal=="failed"))
    assert tab.btn_render.isEnabled() and not tab.btn_cancel.isEnabled()
    tab._set_queue_btn_state(running=True)
    assert not tab.btn_queue_start.isEnabled() and tab.btn_queue_pause.isEnabled()
    tab._set_queue_btn_state(running=False)
    assert tab.btn_queue_start.isEnabled() and not tab.btn_queue_pause.isEnabled()


@pytest.mark.parametrize("state,blocked", [("preparing",True),("rendering",True),("finalizing",True),("cancelling",True),("completed",False),("cancelled",False),("failed",False)])
def test_cache_lock_tracks_render_terminal_states(state, blocked):
    from src.gui.qt.tabs.settings_tab import SettingsTab
    tab = SettingsTab()
    tab._on_render_state(SimpleNamespace(state=state))
    assert tab.btn_clear_cache.isEnabled() is not blocked


def test_license_documents_resolve_from_application_root_not_cwd(tmp_path, monkeypatch, qapp):
    from src.gui.qt.license_dialog import LicenseDialog, license_documents
    root = tmp_path / "portable"
    (root / "python/Lib/site-packages/component-1.dist-info/licenses").mkdir(parents=True)
    (root / "THIRD_PARTY_NOTICES.txt").write_text("Actual bundled notices")
    (root / "python/LICENSE.txt").write_text("Actual Python licence")
    license_file = root / "python/Lib/site-packages/component-1.dist-info/licenses/LICENSE"
    license_file.write_text("Real component copyright")
    (license_file.parent / "LGPL-3.0-only.txt").write_text("Actual packaged licence terms")
    monkeypatch.chdir(tmp_path)
    docs = license_documents(root)
    assert len(docs) == 4 and all(p.is_relative_to(root) for _, p in docs)
    dialog = LicenseDialog(root)
    dialog.show()
    for _ in range(100):
        qapp.processEvents()
        if dialog.documents.count(): break
        QTest.qWait(10)
    assert dialog.documents.count() == 4
    for i in range(dialog.documents.count()):
        dialog.documents.setCurrentIndex(i)
        assert dialog.text.toPlainText() == Path(dialog.documents.currentData()).read_text()
    assert dialog.text.isReadOnly()


@pytest.mark.parametrize("parent,child,off,on", [
    ("show_marker","marker_style",False,True),
    ("marker_style","marker_size","none","dot"),
    ("show_label","label_font_size",False,True),
    ("show_value","decimals",False,True),
    ("show_min","range_gap",False,True),
    ("show_max","range_gap",False,True),
    ("segment_color_mode","segment_color","gradient","solid"),
    ("segment_color_mode","segment_color_start","solid","gradient"),
    ("segment_color_mode","gradient_space","solid","gradient"),
    ("segment_color_mode","segment_thresholds","solid","threshold"),
    ("grow_height","grow_start",False,True),
    ("segment_shape","segment_corner_radius","square","rounded"),
    ("auto_scale","min_val",True,False),
    ("auto_scale","max_val",True,False),
    ("outline_enabled","outline_width",False,True),
    ("shadow_enabled","shadow_distance",False,True),
])
def test_property_dependencies_disable_and_restore_real_fields(parent, child, off, on):
    from src.gui.qt.models import FieldSchema
    from src.gui.qt.widgets.property_editor import PropertyEditor
    editor = PropertyEditor()
    is_bool = isinstance(off, bool)
    parent_schema = FieldSchema(parent, "bool" if is_bool else "choice", parent,
                                choices=None if is_bool else [off,on])
    if child == "marker_style":
        child_schema = FieldSchema(child, "choice", child, choices=["none","dot"])
    else:
        child_schema = FieldSchema(child, "float", child, min_val=0, max_val=100)
    values = {parent:off, "show_min":False, "show_max":False}
    values[parent] = off
    schema = [parent_schema,child_schema]
    if parent in ("show_min", "show_max"):
        other = "show_max" if parent == "show_min" else "show_min"
        schema.append(FieldSchema(other, "bool", other, default=False))
    editor.on_properties_ready("fixture", schema, values)
    assert not editor._field_widgets[child].isEnabled()
    values[parent] = on
    spy = QSignalSpy(editor.signals.sig_property_changed)
    editor.update_field_values(values)
    assert editor._field_widgets[child].isEnabled()
    assert spy.count() == 0
    editor.on_properties_ready("", [], {})
    assert editor.delete_btn.isHidden() and editor.scroll_area.isHidden()
