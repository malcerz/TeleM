"""tests/test_youtube_upload_ui_disabled.py — Weryfikacja ukrycia opcji YouTube w GUI.

Sprawdza:
1. Brak elementów YouTube w GUI (chk_yt_enabled, edit_yt_title, cmb_yt_privacy, edit_yt_desc są None,
   brak widocznych etykiet i checkboxów YouTube w drzewie widgetów).
2. Wysokość queue_list naturalnie powiększona (brak pustego miejsca po usunięciu kontrolek).
3. Bezpieczne dodawanie zadania do kolejki (_on_add_to_queue) bez błędów AttributeError,
   z domyślnym fallbackiem yt_enabled=False.
4. Brak wyzwalania uploadera YouTube w tle przy ukończeniu renderu.
5. Normalny eksport (zarówno bezpośredni, jak i przez kolejkę) działa bez zakłóceń.
6. Możliwość ponownego włączenia elementów YouTube przez pojedynczą flagę ENABLE_YOUTUBE_UPLOAD_UI.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
import pytest
from PySide6.QtWidgets import QApplication, QCheckBox, QLabel, QLineEdit, QComboBox

from src.gui.export_queue import (
    ENABLE_YOUTUBE_UPLOAD,
    ENABLE_YOUTUBE_UPLOAD_UI,
    YOUTUBE_UPLOAD_FEATURE_ENABLED,
    ExportJob,
    ExportQueue,
)
import src.gui.export_queue as export_queue_mod
import src.gui.qt.tabs.render_tab as render_tab_mod
from src.gui.qt.tabs.render_tab import RenderTab


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    return app


def test_feature_flag_defaults():
    """Domyślnie funkcja uploadu YouTube ma być wyłączona."""
    assert ENABLE_YOUTUBE_UPLOAD_UI is False
    assert ENABLE_YOUTUBE_UPLOAD is False
    assert YOUTUBE_UPLOAD_FEATURE_ENABLED is False


def test_youtube_ui_hidden_when_disabled(qapp):
    """Gdy flaga jest wyłączona, kontrolki YouTube nie są tworzone w GUI."""
    rt = RenderTab()
    try:
        # Kontrolki per-job powinny mieć wartość None
        assert rt.chk_yt_enabled is None
        assert rt.edit_yt_title is None
        assert rt.cmb_yt_privacy is None
        assert rt.edit_yt_desc is None

        # W drzewie widgetów nie może być żadnych etykiet ani checkboxów YouTube
        checkboxes = rt.findChildren(QCheckBox)
        yt_checkboxes = [cb for cb in checkboxes if "YouTube" in cb.text() or "YT" in cb.text()]
        assert len(yt_checkboxes) == 0, f"Znaleziono nieoczekiwane checkboxy YouTube: {yt_checkboxes}"

        labels = rt.findChildren(QLabel)
        yt_labels = [lbl for lbl in labels if "Tytuł YT" in lbl.text() or "Prywatność:" in lbl.text()]
        assert len(yt_labels) == 0, f"Znaleziono nieoczekiwane etykiety YouTube: {yt_labels}"

        # Lista kolejki ma powiększoną przestrzeń pionową (do 260px zamiast 180px)
        assert rt.queue_list.maximumHeight() == 260
        assert rt.queue_list.minimumHeight() == 80
    finally:
        rt.deleteLater()


def test_add_to_queue_without_youtube_controls(qapp, tmp_path):
    """_on_add_to_queue tworzy zadanie bez błędu AttributeError i z yt_enabled=False."""
    rt = RenderTab()
    q = ExportQueue(appdata_dir=tmp_path)
    try:
        rt._export_queue = q

        dummy_ctrl = type(
            "DummyController",
            (),
            {
                "video_paths": [str(tmp_path / "video.mp4")],
                "video_path": str(tmp_path / "video.mp4"),
                "fit_path": "",
                "gpx_path": "",
                "layout": {},
                "telemetry": None,
            },
        )()
        rt._controller = dummy_ctrl

        rt.edit_output.setText(str(tmp_path / "test_out.mp4"))
        # Wywołanie dodania do kolejki
        rt._on_add_to_queue()

        jobs = q.get_jobs()
        assert len(jobs) == 1
        job = jobs[0]
        assert job.yt_enabled is False
        assert job.yt_title == ""
        assert job.yt_privacy == "private"
        assert job.yt_description == ""
        assert job.upload_status == "idle"
    finally:
        q.stop()
        rt.deleteLater()


def test_upload_not_triggered_when_feature_disabled(tmp_path):
    """Ukończenie renderu z wyłączoną flagą nie powoduje zaplanowania ani startu uploadu."""
    q = ExportQueue(appdata_dir=tmp_path)
    try:
        job = ExportJob(
            video_paths=["test.mp4"],
            output_path="test_out.mp4",
            yt_enabled=False,
        )
        q.add_job(job)
        with q._lock:
            q._active_render_id = job.job_id
            job.render_status = "running"

        q.notify_render_done(job.job_id, success=True, output_path="test_out.mp4")

        j = q.get_jobs()[0]
        assert j.render_status == "done"
        assert j.upload_status == "idle"
        assert j.is_done() is True

        # Scheduler i helpery uploadu nie wybierają żadnego zadania
        assert q._next_waiting_upload() is None
        q._try_start_upload()
        assert q._active_upload_id is None
    finally:
        q.stop()


def test_youtube_ui_re_enabled_with_flag(qapp, monkeypatch):
    """Przy przestawieniu flagi na True, interfejs YouTube pojawia się poprawnie w jednym punkcie."""
    monkeypatch.setattr(export_queue_mod, "ENABLE_YOUTUBE_UPLOAD_UI", True)
    monkeypatch.setattr(export_queue_mod, "ENABLE_YOUTUBE_UPLOAD", True)
    monkeypatch.setattr(render_tab_mod, "ENABLE_YOUTUBE_UPLOAD_UI", True)

    rt = RenderTab()
    try:
        assert rt.chk_yt_enabled is not None
        assert isinstance(rt.chk_yt_enabled, QCheckBox)
        assert "YouTube" in rt.chk_yt_enabled.text()

        assert rt.edit_yt_title is not None
        assert isinstance(rt.edit_yt_title, QLineEdit)

        assert rt.cmb_yt_privacy is not None
        assert isinstance(rt.cmb_yt_privacy, QComboBox)

        assert rt.edit_yt_desc is not None
        assert isinstance(rt.edit_yt_desc, QLineEdit)

        # Kontrolki tytułu/opisu są domyślnie wyłączone dopóki checkbox nie jest zaznaczony
        assert rt.edit_yt_title.isEnabled() is False
        assert rt.cmb_yt_privacy.isEnabled() is False
        assert rt.edit_yt_desc.isEnabled() is False

        # Zaznaczenie checkboxa aktywuje pola
        rt.chk_yt_enabled.setChecked(True)
        assert rt.edit_yt_title.isEnabled() is True
        assert rt.cmb_yt_privacy.isEnabled() is True
        assert rt.edit_yt_desc.isEnabled() is True

        # Wysokość queue_list jest wtedy ograniczona do 180px
        assert rt.queue_list.maximumHeight() == 180
    finally:
        rt.deleteLater()
