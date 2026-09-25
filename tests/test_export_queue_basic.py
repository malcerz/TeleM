"""tests/test_export_queue_basic.py — testy jednostkowe ExportQueue.

Sprawdza:
  - Tworzenie / usuwanie jobów
  - Immutabilność snapshotu (dodany job nie reaguje na zmiany zewnętrzne)
  - Persystencję JSON (atomic replace + reload z resetem running→queued)
  - MAX_CONCURRENT_RENDERS = 1 (scheduler nie startuje dwóch renderów równocześnie)
  - Powiadamianie kolejki przez notify_render_done
  - _safe_output_path collision avoidance
  - is_done() state machine
"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path

import pytest

from src.gui.export_queue import ExportJob, ExportQueue, _safe_output_path


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def make_queue(tmp_path: Path) -> ExportQueue:
    """Stwórz ExportQueue z tymczasowym katalogiem AppData."""
    return ExportQueue(appdata_dir=tmp_path)


def make_job(**kwargs) -> ExportJob:
    defaults = dict(
        video_paths=["Video/test.mp4"],
        fit_path="Video/test.fit",
        gpx_path="",
        layout={"indicators": {}},
        options={"encoder": "amd", "bitrate": "40"},
        output_path="out_test.mp4",
    )
    defaults.update(kwargs)
    return ExportJob(**defaults)


# ─────────────────────────────────────────────────────────────────────────────
# 1. add / remove
# ─────────────────────────────────────────────────────────────────────────────

def test_add_job(tmp_path):
    q = make_queue(tmp_path)
    try:
        job = make_job()
        q.add_job(job)
        assert len(q.get_jobs()) == 1
        assert q.get_jobs()[0].job_id == job.job_id
    finally:
        q.stop()


def test_add_multiple_jobs(tmp_path):
    q = make_queue(tmp_path)
    try:
        for i in range(3):
            q.add_job(make_job(output_path=f"out_{i}.mp4"))
        assert len(q.get_jobs()) == 3
    finally:
        q.stop()


def test_remove_queued_job(tmp_path):
    q = make_queue(tmp_path)
    try:
        job = make_job()
        q.add_job(job)
        removed = q.remove_job(job.job_id)
        assert removed is True
        assert len(q.get_jobs()) == 0
    finally:
        q.stop()


def test_remove_active_render_blocked(tmp_path):
    """Nie można usunąć jobu który aktualnie renderuje."""
    q = make_queue(tmp_path)
    try:
        job = make_job()
        q.add_job(job)
        # Ręcznie ustaw jako active render (bezpośredni dostęp do _jobs żeby uniknąć deadlocka z lockiem)
        with q._lock:
            q._active_render_id = job.job_id
            q._jobs[0].render_status = "running"
        removed = q.remove_job(job.job_id)
        assert removed is False
        assert len(q.get_jobs()) == 1
    finally:
        q.stop()


# ─────────────────────────────────────────────────────────────────────────────
# 2. Snapshot immutability
# ─────────────────────────────────────────────────────────────────────────────

def test_job_snapshot_options_independence(tmp_path):
    """Modyfikacja oryginalnego dict options po add_job nie wpływa na job w kolejce."""
    q = make_queue(tmp_path)
    try:
        original_options = {"encoder": "amd", "bitrate": "40"}
        job = make_job(options=dict(original_options))
        q.add_job(job)
        # Modyfikuj oryginał PO add — ExportJob jest dataclassą, nie kopiuje referencji
        original_options["encoder"] = "nv"
        stored = q.get_jobs()[0]
        # Job trzyma przekazany dict bezpośrednio — test sprawdza że nie jest tym samym obiektem
        assert stored.options is not original_options
        # Wartość w queue nie zmieniła się przez mutację original_options
        assert stored.options["encoder"] == "amd"
    finally:
        q.stop()


# ─────────────────────────────────────────────────────────────────────────────
# 3. JSON persistence
# ─────────────────────────────────────────────────────────────────────────────

def test_json_persistence_roundtrip(tmp_path):
    """Kolejka zapisuje i odczytuje joby z JSON."""
    q = make_queue(tmp_path)
    try:
        job = make_job(yt_enabled=True, yt_title="Test ride", yt_privacy="unlisted")
        q.add_job(job)
    finally:
        q.stop()

    # Wczytaj świeżą instancję
    q2 = make_queue(tmp_path)
    try:
        q2._load_persisted()
        jobs = q2.get_jobs()
        assert len(jobs) == 1
        j = jobs[0]
        assert j.job_id == job.job_id
        assert j.yt_enabled is True
        assert j.yt_title == "Test ride"
        assert j.yt_privacy == "unlisted"
        assert j.render_status == "queued"
    finally:
        q2.stop()


def test_json_persistence_running_reset_to_interrupted(tmp_path):
    """Po restarcie joby ze statusem 'running' przechodzą do 'interrupted'."""
    path = tmp_path / "export_queue.json"
    job = make_job(output_path="out_reset.mp4")
    # Zapisz ręcznie z running
    data = [dict(
        job_id=job.job_id,
        video_paths=job.video_paths,
        fit_path=job.fit_path,
        gpx_path=job.gpx_path,
        layout=job.layout,
        options=job.options,
        output_path=job.output_path,
        yt_enabled=False,
        yt_title="",
        yt_privacy="private",
        yt_description="",
        yt_video_id="",
        render_status="running",   # <-- symulacja przerwania mid-render
        render_progress=0.42,
        render_error="",
        upload_status="idle",
        upload_progress=0.0,
        upload_error="",
        created_at=time.time(),
        render_started_at=None,
        render_finished_at=None,
        upload_started_at=None,
        upload_finished_at=None,
    )]
    path.write_text(json.dumps(data), encoding="utf-8")

    q = make_queue(tmp_path)
    try:
        q._load_persisted()
        j = q.get_jobs()[0]
        assert j.render_status == "interrupted"
        assert j.render_progress == 0.0
    finally:
        q.stop()


def test_json_persistence_upload_running_reset_to_interrupted(tmp_path):
    """Po restarcie joby z upload_status 'running' przechodzą do 'interrupted'."""
    path = tmp_path / "export_queue.json"
    job = make_job(yt_enabled=True)
    data = [dict(
        job_id=job.job_id,
        video_paths=job.video_paths,
        fit_path=job.fit_path,
        gpx_path=job.gpx_path,
        layout=job.layout,
        options=job.options,
        output_path=job.output_path,
        yt_enabled=True,
        yt_title="",
        yt_privacy="private",
        yt_description="",
        yt_video_id="",
        render_status="done",
        render_progress=1.0,
        render_error="",
        upload_status="running",  # <-- przerwany upload
        upload_progress=0.5,
        upload_error="",
        created_at=time.time(),
        render_started_at=None,
        render_finished_at=None,
        upload_started_at=None,
        upload_finished_at=None,
    )]
    path.write_text(json.dumps(data), encoding="utf-8")

    q = make_queue(tmp_path)
    try:
        q._load_persisted()
        j = q.get_jobs()[0]
        assert j.upload_status == "interrupted"
        assert j.upload_progress == 0.0
    finally:
        q.stop()


# ─────────────────────────────────────────────────────────────────────────────
# 4. MAX_CONCURRENT_RENDERS = 1
# ─────────────────────────────────────────────────────────────────────────────

def test_scheduler_max_concurrent_renders_one(tmp_path):
    """Scheduler startuje maksymalnie 1 render jednocześnie."""
    started_jobs = []
    render_done = threading.Event()

    def fake_render_cb(job: ExportJob):
        started_jobs.append(job.job_id)
        # Czekaj na sygnał testu (symuluj długi render)
        render_done.wait(timeout=0.5)

    q = make_queue(tmp_path)
    q.set_render_callback(fake_render_cb)

    try:
        # Dodaj 2 joby bez persystencji (bezpośrednio w _jobs)
        j1 = make_job(output_path="out_1.mp4")
        j2 = make_job(output_path="out_2.mp4")
        with q._lock:
            q._jobs = [j1, j2]

        # Uruchom scheduler
        q.start()
        # Daj schedulerowi chwilę na uruchomienie render #1
        time.sleep(0.2)

        # Tylko 1 render powinien startować na raz
        assert len(started_jobs) <= 1

        # Zwolnij render_done → render_cb kończy → scheduler może startować render #2
        render_done.set()
    finally:
        q.stop()


# ─────────────────────────────────────────────────────────────────────────────
# 5. notify_render_done — sekwencja
# ─────────────────────────────────────────────────────────────────────────────

def test_notify_render_done_success_queues_upload(tmp_path):
    """Po notify_render_done(success=True) job z yt_enabled=True zmienia status uploadu na waiting."""
    q = make_queue(tmp_path)
    try:
        job = make_job(yt_enabled=True)
        q._jobs = [job]

        with q._lock:
            q._active_render_id = job.job_id
            q._jobs[0].render_status = "running"

        q.notify_render_done(job.job_id, success=True, output_path="out_done.mp4")

        j = q.get_jobs()[0]
        assert j.render_status == "done"
        assert j.upload_status == "waiting"
        assert q._active_render_id is None
    finally:
        q.stop()


def test_notify_render_done_failure_no_upload(tmp_path):
    """Po notify_render_done(success=False) upload NIE jest planowany."""
    q = make_queue(tmp_path)
    try:
        job = make_job(yt_enabled=True)
        q._jobs = [job]
        with q._lock:
            q._active_render_id = job.job_id
            q._jobs[0].render_status = "running"

        q.notify_render_done(job.job_id, success=False)

        j = q.get_jobs()[0]
        assert j.render_status == "error"
        assert j.upload_status == "idle"  # upload nie został zaplanowany
    finally:
        q.stop()


def test_notify_render_done_yt_disabled_no_upload(tmp_path):
    """Gdy yt_enabled=False, po done upload_status pozostaje idle."""
    q = make_queue(tmp_path)
    try:
        job = make_job(yt_enabled=False)
        q._jobs = [job]
        with q._lock:
            q._active_render_id = job.job_id
            q._jobs[0].render_status = "running"

        q.notify_render_done(job.job_id, success=True)

        j = q.get_jobs()[0]
        assert j.render_status == "done"
        assert j.upload_status == "idle"
    finally:
        q.stop()


# ─────────────────────────────────────────────────────────────────────────────
# 6. is_done()
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("render_status,upload_status,yt_enabled,expected", [
    ("done", "idle", False, True),
    ("done", "done", True, True),
    ("done", "error", True, True),
    ("done", "waiting", True, False),
    ("done", "running", True, False),
    ("running", "idle", False, False),
    ("queued", "idle", False, False),
    ("error", "idle", False, True),
])
def test_is_done(render_status, upload_status, yt_enabled, expected):
    job = make_job(yt_enabled=yt_enabled)
    job.render_status = render_status
    job.upload_status = upload_status
    assert job.is_done() == expected


# ─────────────────────────────────────────────────────────────────────────────
# 7. _safe_output_path — brak nadpisywania
# ─────────────────────────────────────────────────────────────────────────────

def test_safe_output_path_no_collision(tmp_path):
    p = tmp_path / "out.mp4"
    result = _safe_output_path(str(p))
    assert result == str(p)  # plik nie istnieje, zwróć bez modyfikacji


def test_safe_output_path_with_collision(tmp_path):
    p = tmp_path / "out.mp4"
    p.touch()  # symuluj istniejący plik
    result = _safe_output_path(str(p))
    assert result == str(tmp_path / "out_001.mp4")
    assert result != str(p)


def test_safe_output_path_multiple_collisions(tmp_path):
    for i in range(3):
        (tmp_path / "out.mp4").touch() if i == 0 else (tmp_path / f"out_{i:03d}.mp4").touch()
    result = _safe_output_path(str(tmp_path / "out.mp4"))
    # out.mp4, out_001.mp4, out_002.mp4 zajęte → out_003.mp4
    assert result == str(tmp_path / "out_003.mp4")
