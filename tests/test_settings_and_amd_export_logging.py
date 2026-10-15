"""Targeted tests: unified settings save, 'Pomiń pauzy' after a queue job and
the configurable AMD export log beside the output MP4.

Persistence goes to an isolated APPDATA and temporary base_dir; the repository
def_layout.json must stay byte-identical.  No video is rendered.
"""

import copy
import hashlib
import json
import multiprocessing as mp
import os
import threading
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtWidgets import QApplication, QMessageBox, QWidget


REPO_ROOT = Path(__file__).resolve().parents[1]
REPO_DEF_LAYOUT = REPO_ROOT / "def_layout.json"


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


def _prefs() -> dict:
    from src.export_paths import load_app_preferences
    return load_app_preferences()


def _controller(tmp_path, def_layout=None):
    """AppController bound to a temporary base_dir (never the repository)."""
    from src.gui.qt.controller import AppController
    from src.export_paths import (
        load_amd_export_logging_enabled,
        load_charts_skip_pauses,
        load_startup_preset,
    )

    base = tmp_path / "app"
    base.mkdir(exist_ok=True)
    (base / "def_layout.json").write_text(
        json.dumps(def_layout or {"global": {"font": "Arial"}, "indicators": {}}), encoding="utf-8"
    )
    ctrl = AppController()
    ctrl.base_dir = base
    ctrl._load_startup_preset()
    # Same order as AppController.__init__.
    ctrl.charts_skip_pauses = load_charts_skip_pauses(base)
    ctrl._apply_global_chart_preferences()
    ctrl._startup_preset_path = load_startup_preset(base)
    ctrl.amd_export_logging_enabled = load_amd_export_logging_enabled()
    ctrl._render_preview = lambda *a, **k: None
    return ctrl


def _settings_tab(base_dir):
    from src.gui.qt.tabs.settings_tab import SettingsTab
    from src.gui.qt.signals import get_signals

    tab = SettingsTab.__new__(SettingsTab)
    QWidget.__init__(tab)
    tab.signals = get_signals()
    tab.base_dir = Path(base_dir)
    tab._render_job_active = False
    tab._analysis_active = False
    tab._garmin_dialog = None
    tab._garmin_busy = False
    tab._build_ui()
    tab._load_integration_settings()
    return tab


# ── 1. Settings ─────────────────────────────────────────────────────────────

def test_startup_preset_saved_only_by_green_button(qapp, tmp_path):
    ctrl = _controller(tmp_path)
    def_layout = ctrl.base_dir / "def_layout.json"
    preset = tmp_path / "my_preset.json"
    preset.write_text(json.dumps({"indicators": {}}), encoding="utf-8")
    tab = _settings_tab(ctrl.base_dir)
    layout_before = def_layout.read_bytes()
    tab.edit_startup_preset.setText(str(preset))
    qapp.processEvents()
    # No automatic save: neither profile nor def_layout.json, nor live state.
    assert "startup_preset" not in _prefs()
    assert def_layout.read_bytes() == layout_before
    assert ctrl._startup_preset_path == ""
    assert _settings_tab(ctrl.base_dir).edit_startup_preset.text() == ""

    tab.btn_save_settings.click()
    assert _prefs()["startup_preset"] == str(preset)
    # The layout save clears _startup_preset in def_layout; the controller
    # still holds the saved value afterwards.
    assert ctrl._startup_preset_path == str(preset)

    # Restart: form and controller restore the value.
    assert _settings_tab(ctrl.base_dir).edit_startup_preset.text() == str(preset)
    restarted = _controller(tmp_path, json.loads(def_layout.read_text(encoding="utf-8")))
    assert restarted._startup_preset_path == str(preset)

    # Clearing the startup preset also needs the green button.
    tab.edit_startup_preset.setText("")
    assert _prefs()["startup_preset"] == str(preset)
    tab.btn_save_settings.click()
    assert _prefs()["startup_preset"] == ""
    assert _controller(tmp_path)._startup_preset_path == ""


def test_legacy_startup_preset_is_read_without_writing(qapp, tmp_path):
    preset = tmp_path / "legacy.json"
    preset.write_text("{}", encoding="utf-8")
    ctrl = _controller(tmp_path, {"_startup_preset": str(preset), "indicators": {}})
    assert ctrl._startup_preset_path == str(preset)
    assert _settings_tab(ctrl.base_dir).edit_startup_preset.text() == str(preset)
    assert "startup_preset" not in _prefs()


def test_clear_export_dir_only_clears_form(qapp, tmp_path):
    from src.export_paths import load_default_export_dir

    target = tmp_path / "exports"
    target.mkdir()
    tab = _settings_tab(tmp_path)
    tab.edit_default_export_dir.setText(str(target))
    tab.btn_save_settings.click()
    assert load_default_export_dir() == str(target)

    tab.btn_clear_export_dir.click()
    assert tab.edit_default_export_dir.text() == ""
    assert load_default_export_dir() == str(target), "Wyczyść must not persist"
    assert _settings_tab(tmp_path).edit_default_export_dir.text() == str(target)

    tab.btn_save_settings.click()
    assert load_default_export_dir() == ""
    assert _settings_tab(tmp_path).edit_default_export_dir.text() == ""


def test_all_settings_restored_after_restart(qapp, tmp_path):
    ctrl = _controller(tmp_path)
    target = tmp_path / "out"
    target.mkdir()
    preset = tmp_path / "p.json"
    preset.write_text("{}", encoding="utf-8")
    tab = _settings_tab(ctrl.base_dir)
    tab.edit_default_export_dir.setText(str(target))
    tab.edit_startup_preset.setText(str(preset))
    tab.chk_skip_pauses.setChecked(True)
    tab.chk_amd_export_logging.setChecked(False)
    tab.cmb_lang.setCurrentText("English")
    tab.btn_save_settings.click()

    prefs = _prefs()
    assert prefs["default_export_dir"] == str(target)
    assert prefs["startup_preset"] == str(preset)
    assert prefs["charts_skip_pauses"] is True
    assert prefs["amd_export_logging_enabled"] is False
    assert prefs["ui_language"] == "English"

    restarted = _settings_tab(ctrl.base_dir)
    assert restarted.edit_default_export_dir.text() == str(target)
    assert restarted.edit_startup_preset.text() == str(preset)
    assert restarted.chk_skip_pauses.isChecked() is True
    assert restarted.chk_amd_export_logging.isChecked() is False
    assert restarted.cmb_lang.currentText() == "English"


# ── 2. Pomiń pauzy after a queue job ───────────────────────────────────────

class _QueueCtrl:
    """Minimal controller: the real global-preference method, no telemetry."""

    def __init__(self, video, global_value):
        from src.gui.qt._mixins.preset_mixin import PresetMixin

        self.video_paths = [Path(video)]
        self.video_path = Path(video)
        self.telemetry = None
        self.charts_skip_pauses = global_value
        self.layout = {"charts_skip_pauses": global_value, "indicators": {}}
        self._chart_data_cache = object()
        self.preview_calls = 0
        self._apply_global_chart_preferences = (
            lambda: PresetMixin._apply_global_chart_preferences(self)
        )

    def _render_preview(self):
        self.preview_calls += 1


def _job(video, skip_value, name):
    from src.gui.export_queue import ExportJob

    return ExportJob(
        video_paths=[str(video)],
        layout={"charts_skip_pauses": skip_value, "indicators": {}},
        options={"encoder": "amd"},
        output_path=str(Path(video).parent / name),
    )


@pytest.mark.parametrize("ending", ["completed", "cancelled", "failed"])
def test_skip_pauses_restored_after_queue_job(qapp, tmp_path, ending):
    from src.gui.qt.tabs.render_tab import RenderTab
    from src.render_progress import RenderProgressState

    video = tmp_path / "ride.mp4"
    video.touch()
    ctrl = _QueueCtrl(video, global_value=True)
    tab = RenderTab()
    tab._controller = ctrl
    tab._export_queue = None

    job1 = _job(video, False, "a.mp4")  # frozen while global was OFF
    job_layout_before = copy.deepcopy(job1.layout)
    tab._restore_job_snapshot_onto_controller(job1)
    assert ctrl.layout["charts_skip_pauses"] is False, "render uses the job snapshot"

    tab._rendering = True
    tab._active_queue_job_id = job1.job_id
    tab._render_state = RenderProgressState(
        generation_id=1,
        state=ending,
        completed=ending == "completed",
        cancelled=ending == "cancelled",
        failed=ending == "failed",
    )
    tab._end_render()
    qapp.processEvents()

    assert ctrl.layout["charts_skip_pauses"] is True, "preview returns to the global value"
    assert ctrl._chart_data_cache is None
    assert ctrl.preview_calls >= 1
    assert job1.layout == job_layout_before, "job snapshot stays unchanged"
    assert ctrl.charts_skip_pauses is True

    # Next queue item gets its own frozen value, not leftovers.
    job2 = _job(video, False, "b.mp4")
    tab._restore_job_snapshot_onto_controller(job2)
    assert ctrl.layout["charts_skip_pauses"] is False
    job3 = _job(video, True, "c.mp4")
    tab._restore_job_snapshot_onto_controller(job3)
    assert ctrl.layout["charts_skip_pauses"] is True


def test_queue_snapshot_freezes_amd_logging_flag(qapp, tmp_path):
    from src.gui.qt.tabs.render_tab import RenderTab

    video = tmp_path / "ride.mp4"
    video.touch()

    class DummyCtrl:
        video_paths = [str(video)]
        video_path = str(video)
        layout = {"charts_skip_pauses": False, "indicators": {}}
        charts_skip_pauses = False
        amd_export_logging_enabled = False
        fit_path = ""
        gpx_path = ""

    tab = RenderTab()
    tab._controller = DummyCtrl()
    tab._init_export_queue()
    tab.edit_output.setText("q1.mp4")
    tab._on_add_to_queue()
    job1 = tab._export_queue.get_jobs()[-1]
    DummyCtrl.amd_export_logging_enabled = True
    tab.edit_output.setText("q2.mp4")
    tab._on_add_to_queue()
    job2 = tab._export_queue.get_jobs()[-1]
    assert job1.options["amd_export_logging_enabled"] is False
    assert job2.options["amd_export_logging_enabled"] is True


# ── 3/4. AMD export log ────────────────────────────────────────────────────

def test_log_path_is_output_name_with_log_suffix():
    from src.ffmpeg.amd_export_log import amd_export_log_path

    assert amd_export_log_path(r"D:\GoPro\SCH\20261015-0752.mp4") == Path(r"D:\GoPro\SCH\20261015-0752.log")
    assert amd_export_log_path(r"A:\20260827-1505.mp4") == Path(r"A:\20260827-1505.log")
    # A temporary sidecar never names the log.
    assert amd_export_log_path(r"D:\x\film.mp4.part") == Path(r"D:\x\film.log")
    assert amd_export_log_path(r"D:\x\film.mp4.part.mp4") == Path(r"D:\x\film.log")


def test_logging_flag_resolution_prefers_job_snapshot():
    from src.ffmpeg.amd_export_log import resolve_amd_export_logging

    assert resolve_amd_export_logging({}, True) is True
    assert resolve_amd_export_logging({}, False) is False
    assert resolve_amd_export_logging({"amd_export_logging_enabled": False}, True) is False
    assert resolve_amd_export_logging({"amd_export_logging_enabled": True}, False) is True
    assert resolve_amd_export_logging(None, None) is True


def test_logging_default_on_and_toggle_reaches_controller(qapp, tmp_path):
    from src.export_paths import load_amd_export_logging_enabled

    assert load_amd_export_logging_enabled() is True
    ctrl = _controller(tmp_path)
    tab = _settings_tab(ctrl.base_dir)
    assert tab.chk_amd_export_logging.isChecked() is True
    assert ctrl.amd_export_logging_enabled is True
    tab.chk_amd_export_logging.setChecked(False)
    assert ctrl.amd_export_logging_enabled is False
    assert "amd_export_logging_enabled" not in _prefs(), "only the green button persists"
    assert _settings_tab(ctrl.base_dir).chk_amd_export_logging.isChecked() is True


from src.gui.qt._mixins.render_mixin import RenderMixin as _RenderMixin


class _PipelineOwner(_RenderMixin):
    """Runs RenderMixin._render_pipeline up to the source preflight."""

    def __init__(self, tmp_path, logging_enabled):
        from types import SimpleNamespace
        missing = tmp_path / "missing_source.MP4"
        self.video_path = missing
        self.video_paths = [missing]
        self.layout = {}
        self.base_dir = tmp_path
        self.amd_export_logging_enabled = logging_enabled
        self.signals = SimpleNamespace(sig_export_path_warning=SimpleNamespace(emit=lambda *a: None))


def _run_pipeline_to_preflight(monkeypatch, tmp_path, owner, options):
    import src.gui.qt._mixins.render_mixin as render_module
    from src.ffmpeg.render_errors import RenderError

    monkeypatch.setattr(render_module, "detect_best_encoder", lambda: "amd")
    monkeypatch.setattr(render_module, "_test_encoder", lambda *_a: True)
    with pytest.raises(RenderError) as info:
        render_module.RenderMixin._render_pipeline(owner, options)
    return info.value


@pytest.mark.parametrize("enabled", [True, False])
def test_global_flag_controls_log_creation_before_mp4(monkeypatch, tmp_path, enabled):
    out_dir = tmp_path / "exports"
    out_dir.mkdir()
    output = out_dir / "20261015-0752.mp4"
    owner = _PipelineOwner(tmp_path, enabled)
    options = {"encoder": "amd", "output": str(output)}
    error = _run_pipeline_to_preflight(monkeypatch, tmp_path, owner, options)
    assert error.code == "SOURCE_MISSING"
    log = out_dir / "20261015-0752.log"
    assert log.is_file() is enabled
    assert options["_amd_export_log_path"] == (str(log) if enabled else "")
    assert not (out_dir / "scratch").exists()
    assert not output.exists()
    if enabled:
        text = log.read_text(encoding="utf-8")
        assert "[AMD EXPORT LOG] session_start=" in text
        assert f"output={output}" in text


def test_queue_snapshot_flag_overrides_global(monkeypatch, tmp_path):
    out_dir = tmp_path / "exports"
    out_dir.mkdir()
    owner = _PipelineOwner(tmp_path, logging_enabled=True)
    options = {
        "encoder": "amd",
        "output": str(out_dir / "queued.mp4"),
        "_queue_job_id": "job-x",
        "amd_export_logging_enabled": False,
    }
    _run_pipeline_to_preflight(monkeypatch, tmp_path, owner, options)
    assert not (out_dir / "queued.log").exists()


def test_saved_off_state_controls_logging_after_restart(qapp, monkeypatch, tmp_path):
    from src.export_paths import load_amd_export_logging_enabled

    ctrl = _controller(tmp_path)
    tab = _settings_tab(ctrl.base_dir)
    tab.chk_amd_export_logging.setChecked(False)
    tab.btn_save_settings.click()
    restarted = _controller(tmp_path)
    assert restarted.amd_export_logging_enabled is False
    assert _settings_tab(ctrl.base_dir).chk_amd_export_logging.isChecked() is False

    out_dir = tmp_path / "exports"
    out_dir.mkdir()
    owner = _PipelineOwner(tmp_path, load_amd_export_logging_enabled())
    _run_pipeline_to_preflight(monkeypatch, tmp_path, owner, {"encoder": "amd", "output": str(out_dir / "f.mp4")})
    assert not (out_dir / "f.log").exists()

    tab.chk_amd_export_logging.setChecked(True)
    tab.btn_save_settings.click()
    owner = _PipelineOwner(tmp_path, load_amd_export_logging_enabled())
    _run_pipeline_to_preflight(monkeypatch, tmp_path, owner, {"encoder": "amd", "output": str(out_dir / "f.mp4")})
    assert (out_dir / "f.log").is_file()


def test_render_mixin_passes_log_path_to_child():
    src = (REPO_ROOT / "src/gui/qt/_mixins/render_mixin.py").read_text(encoding="utf-8")
    call = src[src.index("child_res = run_amd_render_child("):]
    call = call[:call.index("out_file = ")]
    assert 'export_log_path=options.get("_amd_export_log_path") or None' in call


def _run_failing_child(tmp_path, output, export_log_path, generation):
    from src.ffmpeg.amd_child_process import run_amd_render_child

    holder = {}
    try:
        run_amd_render_child(
            render_kwargs={
                "generation_id": generation,
                "output_file": output,
                "unexpected_render_argument": True,
            },
            preview_config=None,
            progress_cb=None,
            on_render_progress=None,
            on_preview_frame=None,
            cancel_event=threading.Event(),
            cancel_reason_provider=None,
            active_process_holder=holder,
            generation_id=generation,
            export_log_path=export_log_path,
        )
    except RuntimeError as exc:
        assert holder.get("process") is None
        return exc
    raise AssertionError("controlled child error was not relayed")


def test_child_log_beside_mp4_error_kept_and_appended(tmp_path):
    from src.ffmpeg.amd_export_log import amd_export_log_path, begin_amd_export_log_session

    output = tmp_path / "film.mp4"
    log = amd_export_log_path(output)
    pids = []
    for generation in (911, 912):  # same output name twice
        begin_amd_export_log_session(log, output=output, job_id=f"job-{generation}", generation_id=generation)
        error = _run_failing_child(tmp_path, output, log, generation)
        assert error.details.get("diagnostics_path") == str(log)
        assert f"Log: {log}" in error.display_message()
        pids.append(error.technical_message)
    assert log.is_file()
    text = log.read_text(encoding="utf-8")
    assert text.count("[AMD EXPORT LOG] session_start=") == 2
    assert "job_id=job-911" in text and "job_id=job-912" in text
    assert "previous sessions kept above" in text
    assert text.count("[AMD CHILD START]") == 2
    assert text.count("[AMD CHILD ERROR]") == 2
    assert "phase=render" in text and "[AMD CHILD TRACEBACK]" in text
    assert not (tmp_path / "scratch").exists()
    assert not list(tmp_path.rglob("amd_child_*.log"))
    # Handles are closed: the file can be renamed right away (Windows locks open files).
    renamed = log.with_name("renamed.log")
    log.rename(renamed)
    renamed.rename(log)


def test_child_without_logging_creates_no_file(tmp_path):
    output = tmp_path / "nolog.mp4"
    error = _run_failing_child(tmp_path, output, None, 913)
    # Error still reaches the GUI in readable form.
    assert "unexpected_render_argument" in str(error)
    assert "diagnostics_path" not in error.details
    assert not list(tmp_path.rglob("*.log"))
    assert not (tmp_path / "scratch").exists()


def test_two_queue_outputs_have_separate_logs(tmp_path):
    from src.ffmpeg.amd_export_log import amd_export_log_path

    for name, generation in (("q_a.mp4", 921), ("q_b.mp4", 922)):
        output = tmp_path / name
        _run_failing_child(tmp_path, output, amd_export_log_path(output), generation)
    assert sorted(p.name for p in tmp_path.glob("*.log")) == ["q_a.log", "q_b.log"]
    assert "generation=921" in (tmp_path / "q_a.log").read_text(encoding="utf-8")
    assert "generation=922" in (tmp_path / "q_b.log").read_text(encoding="utf-8")


def test_session_end_status_written_for_cancel_and_error(tmp_path):
    from src.gui.qt._mixins.render_mixin import RenderMixin
    from src.ffmpeg.amd_export_log import begin_amd_export_log_session

    log = tmp_path / "c.log"
    begin_amd_export_log_session(log, output=tmp_path / "c.mp4")
    RenderMixin._finish_amd_export_log({"_amd_export_log_path": str(log)}, "cancelled")
    begin_amd_export_log_session(log, output=tmp_path / "c.mp4")
    RenderMixin._finish_amd_export_log({"_amd_export_log_path": str(log)}, "failed", "boom")
    RenderMixin._finish_amd_export_log({"_amd_export_log_path": ""}, "completed")
    text = log.read_text(encoding="utf-8")
    assert "status=cancelled" in text and "status=failed" in text and "detail=boom" in text
    assert "status=completed" not in text
    log.rename(tmp_path / "moved.log")  # no open handle left


def test_render_error_message_shows_mp4_and_log():
    from src.ffmpeg.render_errors import RenderError

    error = RenderError(
        user_message="Eksport zakończył się błędem.",
        output_path=r"D:\GoPro\SCH\film.mp4",
        details={"diagnostics_path": r"D:\GoPro\SCH\film.log"},
    )
    message = error.display_message()
    assert r"D:\GoPro\SCH\film.mp4" in message
    assert r"Log: D:\GoPro\SCH\film.log" in message
