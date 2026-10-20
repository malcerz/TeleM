"""Targeted tests: consistent AMD VBR QP status in all GUI elements
(direct export and export queue)."""

import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtWidgets import QApplication

from src.render_progress import (
    RenderProgressState,
    RenderProgressTracker,
    format_render_progress_status,
)


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture(autouse=True)
def isolated_profile(monkeypatch, tmp_path):
    monkeypatch.setenv("APPDATA", str(tmp_path / "roaming"))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))


def _hud_states(**frame_extra):
    states = []
    tracker = RenderProgressTracker(total_frames=100, callback=lambda *a: states.append(a[4]), target_fps=30.0)
    tracker.frame(completed=50, elapsed=1.5, fps=33.0, **frame_extra)
    return states[-1]


def _rendering_tab(queue=False):
    """RenderTab in the 'rendering' state for generation 1 (direct or queue job)."""
    from src.gui.qt.tabs.render_tab import RenderTab

    tab = RenderTab()
    tab._rendering = True
    tab._render_generation_id = 1
    if queue:
        class Q:
            progress = []
            def notify_render_progress(self, job_id, pct, phase=""):
                self.progress.append((job_id, pct, phase))
        tab._export_queue = Q()
        tab._active_queue_job_id = "job-1"
    return tab


# AMD AMF QP metrics restored for AMD only (commit d66bc7002c39b4f7b21e33a4c0cf8cdd38bc77ea).
# Status bar and tab display real QP or N/A when rate_control is VBR (AMD).
# Non-AMD backends (Intel/NVIDIA) never show QP.
def test_amd_vbr_without_driver_qp_shows_na(qapp):
    text = "RC: VBR | QP avg: N/A"
    snap = RenderProgressState(generation_id=1, state="rendering", phase="render", frame=4450,
                               total_frames=70995, fps=36.3, elapsed_s=120.0,
                               compression_text=text, rate_control="VBR")
    status_bar = format_render_progress_status(snap)
    assert "Frame: 4450 / 70995" in status_bar
    assert "RC: VBR | QP avg: N/A" in status_bar
    assert "QP: --" not in status_bar

    for queue in (False, True):
        tab = _rendering_tab(queue=queue)
        tab._on_render_state(snap)
        assert "RC: VBR | QP avg: N/A" in tab.lbl_stats.text(), f"queue={queue}"


def test_amd_vbr_with_driver_qp_displayed(qapp):
    text = "RC: VBR | QP: 24 | QP avg: 27.3"
    snap = RenderProgressState(generation_id=1, state="rendering", phase="render", frame=10,
                               total_frames=100, fps=30.0, elapsed_s=1.0, qp=24.0, avg_qp=27.3,
                               compression_text=text, rate_control="VBR")
    status_bar = format_render_progress_status(snap)
    assert text in status_bar
    for queue in (False, True):
        tab = _rendering_tab(queue=queue)
        tab._on_render_state(snap)
        assert text in tab.lbl_stats.text(), f"queue={queue}"


def test_non_amd_status_never_shows_qp(qapp):
    """NVIDIA/Intel do not set rate_control; legacy QP fields are still not shown."""
    snap = RenderProgressState(generation_id=1, state="rendering", phase="render", frame=10,
                               total_frames=100, fps=30.0, elapsed_s=1.0, qp=24.0, avg_qp=27.2,
                               compression_text="QP śr: 27.2 | P90: 30 | q teraz: 24 | 50.0 Mbps")
    tab = _rendering_tab()
    tab._on_render_state(snap)
    assert "QP" not in tab.lbl_stats.text()


def test_preparing_status_formatter_does_not_crash():
    snap = RenderProgressState(generation_id=1, state="preparing", prep_total=10, prep_done=3)
    assert "HUD: 3 / 10" in format_render_progress_status(snap)


def test_render_mixin_snapshot_carries_rate_control_direct_and_queue():
    """Direct and queue renders share one callback: the snapshot keeps RC/QP text for both."""
    import inspect
    from src.gui.qt._mixins import render_mixin

    src = inspect.getsource(render_mixin)
    assert 'rate_control=str(hud_state.get("rate_control"' in src
    # The AMD child path is chosen independently of queue/direct mode.
    child_cond = src[src.index("amd_child_enabled = ("):src.index("amd_child_enabled = (") + 600]
    assert "_queue_job_id" not in child_cond


def test_amd_exporter_reports_rate_control_with_real_qp():
    src = (Path(__file__).resolve().parents[1] / "src/ffmpeg/amd_native_exporter.py").read_text(encoding="utf-8")
    assert 'rate_control="VBR"' in src
    assert "telem_amd_get_encoder_qp_stats" in src
    assert "qp_samples_val" in src
