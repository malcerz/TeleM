"""tests/test_export_queue_lifecycle.py — testy cyklu życia i naprawy 0% freeze ExportQueue.

Sprawdza wymagane scenariusze z sekcji 15:
1. test_queue_job_does_not_enter_rendering_before_worker_start
2. test_queue_dispatch_calls_canonical_render_entrypoint
3. test_queue_progress_updates_job
4. test_queue_render_failure_sets_failed_not_stuck
5. test_queue_start_watchdog
6. test_job1_done_starts_job2
"""

from __future__ import annotations

import os
import threading
import time
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from src.gui.export_queue import (
    ExportJob,
    ExportQueue,
    validate_job_snapshot,
)


def make_queue(tmp_path: Path) -> ExportQueue:
    """Stwórz ExportQueue ze świeżym tymczasowym plikiem JSON."""
    q = ExportQueue()
    q._appdata = tmp_path
    q._queue_path = tmp_path / "export_queue.json"
    q._jobs = []
    q._active_render_id = None
    q._active_upload_id = None
    q._paused = True
    return q


def make_job(tmp_path: Path, name: str = "test", **kwargs) -> ExportJob:
    vid = tmp_path / f"{name}.mp4"
    if not vid.exists():
        vid.write_bytes(b"dummy")
    defaults = dict(
        video_paths=[str(vid)],
        fit_path=str(tmp_path / f"{name}.fit"),
        gpx_path="",
        layout={"indicators": {"speed": {"x": 10}}},
        options={"encoder": "amd", "bitrate": "40M", "render_mode": "gpu"},
        output_path=str(tmp_path / f"out_{name}.mp4"),
    )
    defaults.update(kwargs)
    return ExportJob(**defaults)


# ── 1. test_queue_job_does_not_enter_rendering_before_worker_start ────────────

def test_queue_job_does_not_enter_rendering_before_worker_start(tmp_path):
    q = make_queue(tmp_path)
    job = make_job(tmp_path, "job1")
    q.add_job(job)

    observed_status = []
    render_dispatched = threading.Event()

    def on_render_pick(j: ExportJob):
        # W momencie wywołania callbacku stan MUSI być "preparing", a NIE "running"
        observed_status.append(j.render_status)
        render_dispatched.set()

    q.set_render_callback(on_render_pick)
    q.start()

    assert render_dispatched.wait(timeout=3.0), "Callback renderu nie został wywołany"
    assert observed_status == ["preparing"], (
        f"Oczekiwano stanu 'preparing' przed startem workera, otrzymano: {observed_status}"
    )

    # Potwierdzenie startu workera przełącza w stan "running"
    q.notify_render_started(job.job_id)
    assert job.render_status == "running"
    q.stop()


# ── 2. test_queue_dispatch_calls_canonical_render_entrypoint ──────────────────

def test_queue_dispatch_calls_canonical_render_entrypoint(tmp_path):
    # Weryfikacja statyczna i dynamiczna obecności kanonicznego punktu wejścia
    from PySide6.QtWidgets import QApplication
    _app = QApplication.instance() or QApplication([])

    from src.gui.qt.tabs.render_tab import RenderTab

    tab = RenderTab()
    assert hasattr(tab, "_start_render"), "RenderTab musi posiadać kanoniczną metodę _start_render"
    assert hasattr(tab, "_build_options_from_gui"), "RenderTab musi posiadać _build_options_from_gui"
    assert hasattr(tab, "_dispatch_queue_job_render"), "RenderTab musi posiadać _dispatch_queue_job_render"

    # Test walidacji snapshotu
    valid_job = make_job(tmp_path, "canon_valid")
    ok, err = validate_job_snapshot(valid_job)
    assert ok is True, f"Poprawny job powinien przejść walidację: {err}"

    invalid_job = make_job(tmp_path, "canon_inv", video_paths=[])
    ok, err = validate_job_snapshot(invalid_job)
    assert ok is False, "Job bez plików wideo nie powinien przejść walidacji"


# ── 3. test_queue_progress_updates_job ────────────────────────────────────────

def test_queue_progress_updates_job(tmp_path):
    q = make_queue(tmp_path)
    job = make_job(tmp_path, "prog_job")
    q.add_job(job)

    updates = []
    q.set_on_job_updated(lambda j: updates.append((j.job_id, j.render_progress)))

    q.notify_render_progress(job.job_id, 0.25)
    assert job.render_progress == 0.25

    q.notify_render_progress(job.job_id, 0.78)
    assert job.render_progress == 0.78

    # Ograniczenie 0..1
    q.notify_render_progress(job.job_id, 1.5)
    assert job.render_progress == 1.0

    q.notify_render_progress(job.job_id, -0.1)
    assert job.render_progress == 0.0


# ── 4. test_queue_render_failure_sets_failed_not_stuck ────────────────────────

def test_queue_render_failure_sets_failed_not_stuck(tmp_path):
    q = make_queue(tmp_path)
    job = make_job(tmp_path, "fail_job")
    q.add_job(job)

    q.notify_render_done(job.job_id, success=False, error_message="Brak pamięci GPU")
    assert job.render_status == "error"
    assert job.render_error == "Brak pamięci GPU"
    assert q._active_render_id is None, "Po błędzie _active_render_id musi zostać zwolniony"


# ── 5. test_queue_start_watchdog ──────────────────────────────────────────────

def test_queue_start_watchdog(tmp_path, monkeypatch):
    monkeypatch.setenv("TELEM_QUEUE_WATCHDOG_TIMEOUT", "0.3")

    q = make_queue(tmp_path)
    job = make_job(tmp_path, "stuck_job")
    q.add_job(job)

    # Callback celowo nic nie robi (zawieszony dispatch)
    q.set_render_callback(lambda j: None)
    q.start()

    # Czekaj na zadziałanie watchdoga (0.3 s + margines)
    deadline = time.time() + 3.0
    while time.time() < deadline:
        if job.render_status == "error":
            break
        time.sleep(0.05)

    assert job.render_status == "error", (
        f"Watchdog powinien zmienić status na 'error', aktualny: {job.render_status}"
    )
    assert "Render worker did not start" in job.render_error
    assert q._active_render_id is None
    q.stop()


# ── 6. test_job1_done_starts_job2 ─────────────────────────────────────────────

def test_job1_done_starts_job2(tmp_path):
    q = make_queue(tmp_path)
    job1 = make_job(tmp_path, "j1")
    job2 = make_job(tmp_path, "j2")
    q.add_job(job1)
    q.add_job(job2)

    picked_jobs = []
    job1_picked = threading.Event()
    job2_picked = threading.Event()

    def on_pick(job: ExportJob):
        picked_jobs.append(job.job_id)
        if job.job_id == job1.job_id:
            job1_picked.set()
        elif job.job_id == job2.job_id:
            job2_picked.set()

    q.set_render_callback(on_pick)
    q.start()

    assert job1_picked.wait(timeout=3.0), "Job 1 nie został pobrany"
    assert job1.job_id in picked_jobs

    # Symuluj udane zakończenie Job 1
    q.notify_render_started(job1.job_id)
    q.notify_render_done(job1.job_id, success=True, output_path=job1.output_path)
    assert job1.render_status == "done"

    # Job 2 powinien automatycznie wystartować bez ponownego klikania Start!
    assert job2_picked.wait(timeout=3.0), "Job 2 nie wystartował automatycznie po Job 1"
    assert picked_jobs == [job1.job_id, job2.job_id]
    assert job2.render_status in ("preparing", "running")

    q.stop()


def test_queue_stop_and_cancelled_status_lifecycle(tmp_path):
    from src.gui.export_queue import ExportQueue, ExportJob
    db_file = tmp_path / 'queue_cancel.json'
    q = make_queue(tmp_path)
    job = ExportJob(video_paths=['a.mp4'], output_path=str(tmp_path / 'out.mp4'))
    q.add_job(job)
    q.start()
    q.notify_render_started(job.job_id)
    assert job.render_status in ('preparing', 'running')
    q.notify_render_done(job.job_id, success=False, cancelled=True, error_message='Anulowano przez uzytkownika')
    assert job.render_status == 'cancelled'
    assert job.render_error == 'Anulowano przez uzytkownika'
    q.stop()


def test_queue_progress_recovers_from_early_watchdog_error(tmp_path):
    from src.gui.export_queue import ExportQueue, ExportJob
    db_file = tmp_path / 'queue_rec.json'
    q = make_queue(tmp_path)
    job = ExportJob(video_paths=['a.mp4'], output_path=str(tmp_path / 'out.mp4'))
    q.add_job(job)
    job.render_status = 'error'
    job.render_error = 'Render worker did not start'
    q.notify_render_progress(job.job_id, 0.05, phase='render')
    assert job.render_status == 'running'
    assert job.render_error == ''
    q.stop()
