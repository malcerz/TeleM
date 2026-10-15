"""Targeted tests: unified settings save and persistent 'Pomiń pauzy aktywności'.

All persistence goes to an isolated APPDATA and a temporary base_dir; the
repository def_layout.json must stay byte-identical.
"""

import hashlib
import json
import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtWidgets import QApplication, QMessageBox, QPushButton, QTabWidget, QWidget


REPO_DEF_LAYOUT = Path(__file__).resolve().parents[1] / "def_layout.json"


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture(autouse=True)
def isolated_profile(monkeypatch, tmp_path):
    monkeypatch.setenv("APPDATA", str(tmp_path / "roaming"))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: QMessageBox.Ok)
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: QMessageBox.Ok)
    before = hashlib.sha256(REPO_DEF_LAYOUT.read_bytes()).hexdigest()
    yield
    assert hashlib.sha256(REPO_DEF_LAYOUT.read_bytes()).hexdigest() == before, \
        "repository def_layout.json must not be modified"


def _controller(tmp_path, def_layout=None):
    """AppController bound to a temporary base_dir (never the repository)."""
    from src.gui.qt.controller import AppController

    base = tmp_path / "app"
    base.mkdir(exist_ok=True)
    (base / "def_layout.json").write_text(
        json.dumps(def_layout or {"global": {"font": "Arial"}, "indicators": {}}), encoding="utf-8"
    )
    ctrl = AppController()
    ctrl.base_dir = base
    ctrl._load_startup_preset()
    from src.export_paths import load_charts_skip_pauses
    ctrl.charts_skip_pauses = load_charts_skip_pauses(base)
    ctrl._apply_global_chart_preferences()
    ctrl._render_preview = lambda *a, **k: None
    return ctrl


def _settings_tab(base_dir):
    from src.gui.qt.tabs.settings_tab import SettingsTab

    tab = SettingsTab.__new__(SettingsTab)
    QWidget.__init__(tab)
    # Same as SettingsTab.__init__ but with a temporary base_dir.
    from src.gui.qt.signals import get_signals
    tab.signals = get_signals()
    tab.base_dir = Path(base_dir)
    tab._render_job_active = False
    tab._analysis_active = False
    tab._garmin_dialog = None
    tab._garmin_busy = False
    tab._build_ui()
    tab._load_integration_settings()
    return tab


# ── 1. Settings: one green save button ──────────────────────────────────────

def test_separate_export_dir_save_button_removed(qapp, tmp_path):
    tab = _settings_tab(tmp_path)
    texts = [b.text() for b in tab.findChildren(QPushButton)]
    assert "Zapisz folder eksportu" not in texts
    assert texts.count("Zapisz ustawienia") == 1
    assert not hasattr(tab, "btn_save_export_dir")
    # Wybierz / Wyczyść keep their meaning.
    assert tab.btn_export_dir.text() == "Wybierz"
    assert tab.btn_clear_export_dir.text() == "Wyczyść"


def test_export_dir_saved_only_by_green_button_and_survives_restart(qapp, tmp_path):
    from src.export_paths import load_default_export_dir

    target = tmp_path / "exports"
    target.mkdir()
    tab = _settings_tab(tmp_path)
    tab.edit_default_export_dir.setText(str(target))
    assert load_default_export_dir() in (None, ""), "edit alone must not persist"
    _settings_tab(tmp_path)  # restart without saving
    assert load_default_export_dir() in (None, "")

    tab.btn_save_settings.click()
    pref = Path(os.environ["APPDATA"]) / "SportCamHUD" / "app_preferences.json"
    assert json.loads(pref.read_text(encoding="utf-8"))["default_export_dir"] == str(target)
    assert _settings_tab(tmp_path).edit_default_export_dir.text() == str(target)


def test_invalid_export_dir_blocks_save(qapp, tmp_path):
    from src.export_paths import load_app_preferences

    tab = _settings_tab(tmp_path)
    tab.chk_skip_pauses.setChecked(True)
    tab.edit_default_export_dir.setText(str(tmp_path / "missing_dir"))
    tab.btn_save_settings.click()
    assert "charts_skip_pauses" not in load_app_preferences()


def test_language_and_theme_saved_by_green_button(qapp, tmp_path):
    tab = _settings_tab(tmp_path)
    tab.cmb_lang.setCurrentText("English")
    tab.btn_save_settings.click()
    restarted = _settings_tab(tmp_path)
    assert restarted.cmb_lang.currentText() == "English"
    assert restarted.cmb_theme.currentText() == tab.cmb_theme.currentText()


# ── 2. Pomiń pauzy aktywności ──────────────────────────────────────────────

@pytest.mark.parametrize("value", [True, False])
def test_skip_pauses_survives_restart(qapp, tmp_path, value):
    # Legacy def_layout holds the opposite value: the saved preference must win.
    ctrl = _controller(tmp_path, {"charts_skip_pauses": (not value), "indicators": {}})
    tab = _settings_tab(ctrl.base_dir)
    assert tab.chk_skip_pauses.isChecked() is (not value), "legacy value restored before first save"

    tab.chk_skip_pauses.setChecked(value)
    assert ctrl.layout["charts_skip_pauses"] is value, "form change updates live state"
    tab.btn_save_settings.click()

    restarted_tab = _settings_tab(ctrl.base_dir)
    restarted_ctrl = _controller(tmp_path, json.loads((ctrl.base_dir / "def_layout.json").read_text(encoding="utf-8")))
    assert restarted_tab.chk_skip_pauses.isChecked() is value
    assert restarted_ctrl.charts_skip_pauses is value
    assert restarted_ctrl.layout["charts_skip_pauses"] is value


def test_unsaved_skip_pauses_change_is_not_persisted(qapp, tmp_path):
    ctrl = _controller(tmp_path)
    tab = _settings_tab(ctrl.base_dir)
    tab.chk_skip_pauses.setChecked(True)
    assert _settings_tab(ctrl.base_dir).chk_skip_pauses.isChecked() is False


def test_skip_pauses_not_reset_by_tab_switch(qapp, tmp_path):
    ctrl = _controller(tmp_path)
    tab = _settings_tab(ctrl.base_dir)
    tabs = QTabWidget()
    other = QWidget()
    tabs.addTab(other, "A")
    tabs.addTab(tab, "Ustawienia")
    tab.chk_skip_pauses.setChecked(True)
    for idx in (0, 1, 0, 1):
        tabs.setCurrentIndex(idx)
        qapp.processEvents()
    assert tab.chk_skip_pauses.isChecked() is True
    assert ctrl.layout["charts_skip_pauses"] is True


def test_project_and_preset_layouts_do_not_reset_global_skip_pauses(qapp, tmp_path, monkeypatch):
    ctrl = _controller(tmp_path)
    ctrl._on_settings_changed("charts_skip_pauses", True)

    # Project/preset layout carrying an opposite (or no) value.
    preset = tmp_path / "preset.json"
    preset.write_text(json.dumps({"charts_skip_pauses": False, "indicators": {}}), encoding="utf-8")
    from PySide6.QtWidgets import QFileDialog
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *a, **k: (str(preset), "JSON (*.json)"))
    ctrl._on_load_preset()
    assert ctrl.layout["charts_skip_pauses"] is True

    ctrl._on_reset_layout()
    assert ctrl.layout["charts_skip_pauses"] is True

    # Direct export after a queue job replaced the controller layout.
    ctrl.layout = {"charts_skip_pauses": False, "indicators": {}}
    ctrl._apply_global_chart_preferences()
    assert ctrl.layout["charts_skip_pauses"] is True


def test_project_mixin_applies_global_skip_pauses_after_layout_load():
    src = (Path(__file__).resolve().parents[1] / "src/gui/qt/_mixins/project_mixin.py").read_text(encoding="utf-8")
    block = src[src.index("# Layout — priorytet:"):src.index("render_tab = getattr(getattr(self, \"ui\", None), \"render_tab\", None)")]
    assert "_apply_global_chart_preferences()" in block


def test_queue_snapshot_receives_current_skip_pauses(qapp, tmp_path):
    from src.gui.qt.tabs.render_tab import RenderTab

    src_dir = tmp_path / "src"
    src_dir.mkdir()
    video = src_dir / "ride.mp4"
    video.touch()

    class DummyCtrl:
        video_paths = [str(video)]
        video_path = str(video)
        default_export_dir = ""
        # Stale layout (e.g. restored from an earlier queue job snapshot).
        layout = {"charts_skip_pauses": False, "indicators": {}}
        charts_skip_pauses = True
        fit_path = ""
        gpx_path = ""

    tab = RenderTab()
    tab._controller = DummyCtrl()
    tab._init_export_queue()
    tab.edit_output.setText("queued.mp4")
    tab._on_add_to_queue()
    job = tab._export_queue.get_jobs()[-1]
    assert job.layout["charts_skip_pauses"] is True

    # Snapshot is frozen: later changes do not alter an already queued job.
    DummyCtrl.charts_skip_pauses = False
    assert job.layout["charts_skip_pauses"] is True
