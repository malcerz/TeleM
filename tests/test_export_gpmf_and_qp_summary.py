from __future__ import annotations

import json
import io
import os
import sys
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from src.ffmpeg.export_stats import live_render_avg_qp, resolve_render_avg_qp
from src.ffmpeg.gpmf_export import attach_original_gpmf, detect_gpmf_stream
from src.gui.export_queue import ExportJob, ExportQueue
from src.gui.qt._mixins.render_mixin import RenderMixin


@pytest.fixture(scope="module")
def qapp():
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication(sys.argv)


def test_live_qp_average_is_used_for_same_generation_popup(qapp, monkeypatch):
    from PySide6.QtWidgets import QMessageBox
    from src.gui.qt.tabs.render_tab import RenderTab
    from src.render_progress import RenderProgressState

    captured = []
    monkeypatch.setattr(QMessageBox, "information", lambda _self, _title, message: captured.append(message))
    tab = RenderTab()
    tab._render_state_enabled = False
    tab._rendering = False
    tab._render_total = 300
    tab._render_start = 0.0
    tab._render_generation_id = 14
    tab._last_export_qp = live_render_avg_qp({"qp_avg": 27.6})
    tab._last_export_qp_generation_id = 14
    tab._render_state = RenderProgressState(generation_id=14, state="completed", completed=True)

    tab._on_finished({"generation_id": 14, "avg_qp": None, "codec": "hevc"}, "out.mp4")
    assert "Średnie QP: 27.6" in captured[0]
    assert resolve_render_avg_qp(
        {"avg_qp": None}, generation_id=14, live_qp=27.6, live_generation_id=14,
    ) == 27.6


def test_missing_live_and_terminal_qp_stays_brak_danych(qapp, monkeypatch):
    from PySide6.QtWidgets import QMessageBox
    from src.gui.qt.tabs.render_tab import RenderTab
    from src.render_progress import RenderProgressState

    captured = []
    monkeypatch.setattr(QMessageBox, "information", lambda _self, _title, message: captured.append(message))
    tab = RenderTab()
    tab._render_state_enabled = False
    tab._rendering = False
    tab._render_total = 1
    tab._render_start = 0.0
    tab._render_generation_id = 15
    tab._last_export_qp = None
    tab._last_export_qp_generation_id = 15
    tab._render_state = RenderProgressState(generation_id=15, state="completed", completed=True)
    tab._on_finished({"generation_id": 15, "avg_qp": None}, "out.mp4")
    assert "Średnie QP: brak danych" in captured[0]


def test_qp_fallback_is_reset_safe_and_missing_qp_stays_missing():
    assert resolve_render_avg_qp(
        {"generation_id": 20, "avg_qp": 18.0}, generation_id=22,
        live_qp=27.6, live_generation_id=22,
    ) is None
    assert resolve_render_avg_qp(
        {"avg_qp": None}, generation_id=22, live_qp=27.6, live_generation_id=21,
    ) is None
    assert resolve_render_avg_qp({"avg_qp": None}, generation_id=22) is None
    assert resolve_render_avg_qp(
        {"codec": "av1", "quant_metric": "base_q_idx", "avg_qp": 27.6},
        generation_id=22, live_qp=27.6, live_generation_id=22,
    ) is None


def test_live_average_capture_and_new_export_reset(qapp):
    from src.gui.qt.tabs.render_tab import RenderTab

    assert live_render_avg_qp({"qp_avg": 27.6, "current_qp": 31}) == 27.6
    assert live_render_avg_qp({"compression_text": "QP avg: 27.6"}) == 27.6
    assert live_render_avg_qp({"is_av1": True, "mean_qp": 27.6}) is None
    tab = RenderTab()
    tab._last_export_qp = 27.6
    tab._last_export_qp_generation_id = 7
    tab._reset_export_qp_state(8)
    assert tab._last_export_qp is None
    assert tab._last_export_qp_generation_id == 8


def test_canonical_qp_fields_precede_live_fallback():
    assert resolve_render_avg_qp(
        {"encoder_stats": {"qp_avg": 25.25}},
        generation_id=5,
        live_qp=27.6,
        live_generation_id=5,
    ) == 25.25
    assert resolve_render_avg_qp({"qp_avg": 26.0}, generation_id=5) == 26.0


def test_render_tab_gpmf_option_defaults_off_and_enters_direct_options(qapp):
    from src.gui.qt.tabs.render_tab import RenderTab

    tab = RenderTab()
    assert not tab.chk_original_gpmf.isChecked()
    options = tab._build_options_from_gui()
    assert options["preserve_original_gpmf"] is False
    tab.chk_original_gpmf.setChecked(True)
    assert tab._build_options_from_gui()["preserve_original_gpmf"] is True
    tab.apply_export_settings({})
    assert not tab.chk_original_gpmf.isChecked()
    tab.apply_export_settings({"preserve_original_gpmf": True})
    assert tab.chk_original_gpmf.isChecked()


def test_gpmf_setting_is_saved_in_project_session_layout(qapp, tmp_path):
    from src.gui.qt._mixins.preset_mixin import PresetMixin
    from src.gui.qt.tabs.render_tab import RenderTab

    tab = RenderTab()
    tab.chk_original_gpmf.setChecked(True)
    session_path = tmp_path / "active_layout.json"

    class Harness(PresetMixin):
        def __init__(self):
            self.layout = {"indicators": {}}
            self.ui = SimpleNamespace(render_tab=tab)
            self.session_path = session_path

        def get_session_layout_path(self):
            return self.session_path

    saved_path = Harness()._save_session_layout()
    saved = json.loads(Path(saved_path).read_text(encoding="utf-8"))
    assert saved["export_settings"]["preserve_original_gpmf"] is True
    tab.apply_export_settings(saved["export_settings"])
    assert tab.chk_original_gpmf.isChecked()


def test_queue_option_persists_and_is_render_option(tmp_path):
    queue = ExportQueue(appdata_dir=tmp_path)
    job = ExportJob(
        video_paths=[str(tmp_path / "source.mp4")],
        fit_path="",
        gpx_path="",
        layout={},
        options={"preserve_original_gpmf": True},
        output_path=str(tmp_path / "out.mp4"),
    )
    queue.add_job(job)
    queue._persist()
    reloaded = ExportQueue(appdata_dir=tmp_path)
    try:
        loaded = reloaded.get_jobs()[0]
        assert loaded.options["preserve_original_gpmf"] is True
        assert loaded.options["preserve_original_gpmf"] is job.options["preserve_original_gpmf"]
    finally:
        queue.stop()
        reloaded.stop()


def test_direct_finalization_off_keeps_output_and_on_reaches_mux(monkeypatch, tmp_path):
    import src.ffmpeg.gpmf_export as gpmf_export

    class Harness(RenderMixin):
        ffmpeg_exe = "ffmpeg"
        ffprobe_exe = "ffprobe"
        video_paths = ["source.mp4"]
        _cut_regions = []
        render_cancel_event = threading.Event()
        render_process_holder = {}

    harness = Harness()
    harness.video_path = tmp_path / "source.mp4"
    off_stats = {"marker": True}
    assert harness._finalize_requested_gpmf(
        {"preserve_original_gpmf": False}, off_stats,
    ) == {"marker": True}

    calls = []
    monkeypatch.setattr(gpmf_export, "attach_original_gpmf", lambda **kwargs: calls.append(kwargs) or {"gpmf_status": "attached"})
    output_path = tmp_path / "out.mp4"
    output_path.write_bytes(b"render")
    raw_output = "out.mp4"
    resolved_output = harness._resolve_render_output_path(raw_output)
    stats = harness._finalize_requested_gpmf(
        {
            "preserve_original_gpmf": True,
            "output": raw_output,
            "_render_output_raw": raw_output,
            "_resolved_output_path": str(resolved_output),
        },
        {},
    )
    assert stats["gpmf_status"] == "attached"
    assert calls[0]["source_paths"] == ["source.mp4"]
    assert calls[0]["output_path"] == resolved_output
    assert calls[0]["output_path"] == harness._resolve_render_output_path(raw_output)


def test_render_output_path_resolves_relative_direct_export_to_source_directory():
    class Harness(RenderMixin):
        video_path = Path(r"D:\Video\GX010298.MP4")

    assert Harness()._resolve_render_output_path("test.mp4") == Path(r"D:\Video\test.mp4")


def test_render_output_path_preserves_absolute_export_path():
    class Harness(RenderMixin):
        video_path = Path(r"D:\Video\GX010298.MP4")

    absolute = Path(r"E:\Exports\test.mp4")
    assert Harness()._resolve_render_output_path(str(absolute)) == absolute


def test_queue_relative_output_uses_same_resolved_path_for_render_and_gpmf(monkeypatch, tmp_path):
    import src.ffmpeg.gpmf_export as gpmf_export

    class Harness(RenderMixin):
        ffmpeg_exe = "ffmpeg"
        ffprobe_exe = "ffprobe"
        video_paths = ["source.mp4"]
        _cut_regions = []
        render_cancel_event = threading.Event()
        render_process_holder = {}

    harness = Harness()
    harness.video_path = tmp_path / "source folder" / "source.mp4"
    raw_output = "queue result.mp4"
    resolved_by_render = harness._resolve_render_output_path(raw_output)
    resolved_by_render.parent.mkdir(parents=True, exist_ok=True)
    resolved_by_render.write_bytes(b"render")
    calls = []
    monkeypatch.setattr(
        gpmf_export, "attach_original_gpmf",
        lambda **kwargs: calls.append(kwargs) or {"gpmf_status": "attached"},
    )

    harness._finalize_requested_gpmf(
        {
            "preserve_original_gpmf": True,
            "_queue_job_id": "queue-relative-path",
            "output": str(resolved_by_render),
            "_render_output_raw": raw_output,
            "_resolved_output_path": str(resolved_by_render),
        },
        {},
    )
    resolved_by_finalizer = Path(calls[0]["output_path"])
    assert resolved_by_finalizer == resolved_by_render
    assert resolved_by_finalizer == harness._resolve_render_output_path(raw_output)


@pytest.mark.parametrize("directory", ["path with spaces", "Zażółć gęślą jaźń"])
def test_render_output_path_supports_spaces_and_unicode(directory, tmp_path):
    class Harness(RenderMixin):
        pass

    source = tmp_path / directory / "GX010298.MP4"
    harness = Harness()
    harness.video_path = source
    assert harness._resolve_render_output_path("test output.mp4") == source.parent / "test output.mp4"


def test_gpmf_finalizer_refuses_missing_resolved_output_with_full_path(monkeypatch, tmp_path):
    import src.ffmpeg.gpmf_export as gpmf_export

    class Harness(RenderMixin):
        ffmpeg_exe = "ffmpeg"
        ffprobe_exe = "ffprobe"
        video_paths = ["source.mp4"]
        _cut_regions = []
        render_cancel_event = threading.Event()
        render_process_holder = {}

    harness = Harness()
    harness.video_path = tmp_path / "source.mp4"
    called = []
    monkeypatch.setattr(gpmf_export, "attach_original_gpmf", lambda **kwargs: called.append(kwargs))
    resolved = harness._resolve_render_output_path("missing.mp4")
    with pytest.raises(FileNotFoundError) as exc_info:
        harness._finalize_requested_gpmf(
            {"preserve_original_gpmf": True, "output": "missing.mp4"},
            {},
        )
    assert str(resolved) in str(exc_info.value)
    assert called == []


def test_gpmd_selection_uses_actual_stream_properties(monkeypatch, tmp_path):
    streams = {
        "streams": [
            {"index": 1, "codec_type": "data", "codec_tag_string": "tmcd", "tags": {"handler_name": "GoPro TCD"}},
            {"index": 4, "codec_type": "data", "codec_name": "bin_data", "codec_tag_string": "gpmd", "tags": {"handler_name": "GoPro MET"}},
        ]
    }
    monkeypatch.setattr(
        "src.ffmpeg.gpmf_export.subprocess.run",
        lambda *_args, **_kwargs: SimpleNamespace(stdout=json.dumps(streams)),
    )
    assert detect_gpmf_stream("ffprobe", tmp_path / "clip.mp4")["index"] == 4


def test_no_gpmf_source_does_not_fail_export(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr("src.ffmpeg.gpmf_export.detect_gpmf_stream", lambda *_: None)
    result = attach_original_gpmf(
        ffmpeg_exe="ffmpeg",
        ffprobe_exe="ffprobe",
        source_paths=[tmp_path / "no-gpmf.mp4"],
        output_path=tmp_path / "rendered.mp4",
    )
    assert result["gpmf_status"] == "source_missing"
    assert not result["gpmf_attached"]
    assert "GPMF: brak strumienia w pliku źródłowym" in capsys.readouterr().out


def test_duration_mismatch_refuses_full_track_attachment(monkeypatch, tmp_path):
    import src.ffmpeg.gpmf_export as gpmf_export

    source = tmp_path / "source.mp4"
    output = tmp_path / "short_render.mp4"
    source.write_bytes(b"source")
    output.write_bytes(b"unchanged")
    durations = iter((100.0, 3.0))
    monkeypatch.setattr(gpmf_export, "detect_gpmf_stream", lambda *_: {"index": 5, "codec_tag_string": "gpmd"})
    monkeypatch.setattr(gpmf_export, "_probe_duration", lambda *_: next(durations))
    result = attach_original_gpmf(
        ffmpeg_exe="ffmpeg", ffprobe_exe="ffprobe",
        source_paths=[source], output_path=output,
    )
    assert result["gpmf_status"] == "duration_mismatch"
    assert output.read_bytes() == b"unchanged"


@pytest.mark.parametrize(
    ("source_paths", "trimmed", "expected"),
    [(["one.mp4", "two.mp4"], False, "unsupported_multifile"), (["one.mp4"], True, "unsupported_trimmed")],
)
def test_trim_and_multifile_gpmf_are_explicitly_unsupported(
    tmp_path, source_paths, trimmed, expected,
):
    output = tmp_path / "rendered.mp4"
    output.write_bytes(b"unchanged")
    result = attach_original_gpmf(
        ffmpeg_exe="ffmpeg", ffprobe_exe="ffprobe",
        source_paths=source_paths, output_path=output, trimmed=trimmed,
    )
    assert result["gpmf_status"] == expected
    assert output.read_bytes() == b"unchanged"


def test_gpmf_attach_cancellation_cleans_temp_and_process(monkeypatch, tmp_path):
    import src.ffmpeg.gpmf_export as gpmf_export

    source = tmp_path / "source.mp4"
    output = tmp_path / "rendered.mp4"
    source.write_bytes(b"src")
    output.write_bytes(b"render")
    monkeypatch.setattr(gpmf_export, "detect_gpmf_stream", lambda *_: {"index": 7, "codec_tag_string": "gpmd"})
    monkeypatch.setattr(gpmf_export, "_probe_duration", lambda *_: 1.0)

    class FakeProcess:
        pid = 99
        returncode = None
        stderr = io.StringIO("")

        def poll(self):
            return None

        def terminate(self):
            self.returncode = 0

        def wait(self, timeout=None):
            return self.returncode

    fake = FakeProcess()
    monkeypatch.setattr(gpmf_export.subprocess, "Popen", lambda *args, **kwargs: fake)
    monkeypatch.setattr(gpmf_export.time, "sleep", lambda _delay: None)
    event = threading.Event()
    event.set()
    holder = {}
    with pytest.raises(RuntimeError, match="cancelled"):
        attach_original_gpmf(
            ffmpeg_exe="ffmpeg", ffprobe_exe="ffprobe",
            source_paths=[source], output_path=output,
            cancel_event=event, active_process_holder=holder,
        )
    assert holder == {}
    assert output.read_bytes() == b"render"
    assert not list(tmp_path.glob("rendered.gpmf-*.mp4"))
