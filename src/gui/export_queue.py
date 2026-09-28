"""Export Queue — kolejka zadań renderowania z opcjonalnym automatycznym uploadem YouTube.

Architektura:
    Render #1 ── DONE ──→ Upload YT #1 ── DONE
                      \\
                       └─→ Render #2 ── DONE ──→ Upload YT #2

Reguły:
    MAX_CONCURRENT_RENDERS = 1
    MAX_CONCURRENT_YOUTUBE_UPLOADS = 1
    Render #2 NIE czeka na zakończenie Upload #1.

Persystencja: export_queue.json w katalogu AppData (BikeRideHUD).
Credentiale YouTube: youtube_client_secret.json + youtube_token.json w tym samym katalogu.
NIE commituj plików credentiali!
"""

from __future__ import annotations

import copy
import json
import logging
import os
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

log = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Tracing & Diagnostics
# ─────────────────────────────────────────────────────────────────────────────

def log_queue_trace(
    event: str,
    *,
    job_id: str = "",
    output_path: str = "",
    input_videos: list | None = None,
    extra: str = "",
) -> None:
    """Jednorazowe i strukturalne logowanie cyklu życia kolejki eksportu.
    
    Wymagane punkty:
    [QUEUE START], [QUEUE PICK JOB], [QUEUE SNAPSHOT RESOLVE], [QUEUE DISPATCH],
    [RENDER WORKER START], [FFMPEG START], [FIRST FRAME], [QUEUE PROGRESS], [RENDER DONE]
    """
    now = time.time()
    tname = threading.current_thread().name
    tid = threading.current_thread().ident
    dt_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
    v_str = str(input_videos or [])
    line = f"[{event}] ts={dt_str} ({now:.4f}) thread={tname}/{tid} job_id={job_id} output_path={output_path} input_videos={v_str} {extra}".strip()
    print(line, flush=True)
    try:
        trace_path = Path("scratch/amd_queue_zero/queue_trace.txt")
        trace_path.parent.mkdir(parents=True, exist_ok=True)
        with open(trace_path, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception as exc:
        print(f"[log_queue_trace] Error writing trace: {exc}", flush=True)


def validate_job_snapshot(job: ExportJob) -> tuple[bool, str]:
    """Sprawdź integralność snapshotu zadania przed rozpoczęciem renderingu."""
    if not job.video_paths:
        return False, "Brak ścieżek plików wideo (input_videos pusty)"
    for vp in job.video_paths:
        if not str(vp).strip():
            return False, "Pusta ścieżka pliku wideo"
        p = Path(vp)
        if not p.exists():
            return False, f"Plik wideo źródłowy nie istnieje: {p}"
    if not str(job.output_path).strip():
        return False, "Pusta ścieżka pliku wyjściowego (output_path)"
    out_p = Path(job.output_path)
    if out_p.parent and not out_p.parent.exists():
        try:
            out_p.parent.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            return False, f"Nie można utworzyć katalogu wyjściowego: {out_p.parent} ({e})"
    if not isinstance(job.layout, dict) or not job.layout:
        return False, "Brak lub nieprawidłowy snapshot layoutu (layout pusty)"
    return True, ""



# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _appdata_dir() -> Path:
    """Zwraca katalog AppData\\Roaming\\BikeRideHUD (tworzy jeśli nie istnieje)."""
    base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    d = base / "BikeRideHUD"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _safe_output_path(path: str) -> str:
    """Jeśli plik już istnieje, dodaje sufiks _001, _002, …"""
    p = Path(path)
    if not p.exists():
        return str(p)
    stem = p.stem
    suffix = p.suffix
    parent = p.parent
    for i in range(1, 999):
        candidate = parent / f"{stem}_{i:03d}{suffix}"
        if not candidate.exists():
            return str(candidate)
    return str(parent / f"{stem}_{int(time.time())}{suffix}")


# ─────────────────────────────────────────────────────────────────────────────
# ExportJob
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class ExportJob:
    """Snapshot jednego zadania renderowania (immutable po dodaniu do kolejki)."""

    # Identyfikator
    job_id: str = field(default_factory=lambda: str(uuid.uuid4()))

    # Pliki źródłowe (snapshot; zmiany po dodaniu do kolejki nie wpływają)
    video_paths: list = field(default_factory=list)  # list[str]
    fit_path: str = ""
    gpx_path: str = ""
    external_gpmf_path: str = ""  # User-supplied external JSON only (never generated cache)
    telemetry_cache_key: str = "" # Optional cache hint; cache reconstructed on miss if needed

    # Konfiguracja renderowania (deep-copy layoutu + opcji w momencie dodania)
    layout: dict = field(default_factory=dict)
    options: dict = field(default_factory=dict)   # encoder, bitrate, resolution, …

    # Plik wyjściowy
    output_path: str = "output.mp4"

    # YouTube (opcjonalne)
    yt_enabled: bool = False
    yt_title: str = ""
    yt_privacy: str = "private"    # "private" | "unlisted" | "public"
    yt_description: str = ""
    yt_video_id: str = ""          # wypełniane po udanym uploadzie

    # Stan renderowania
    render_status: str = "queued"   # queued | preparing | running | done | error | cancelled | interrupted
    render_progress: float = 0.0    # 0..1
    render_error: str = ""

    # Stan uploadu
    upload_status: str = "idle"     # idle | waiting | running | done | error | interrupted
    upload_progress: float = 0.0    # 0..1
    upload_error: str = ""

    # Czasy
    created_at: float = field(default_factory=time.time)
    render_started_at: Optional[float] = None
    render_finished_at: Optional[float] = None
    upload_started_at: Optional[float] = None
    upload_finished_at: Optional[float] = None

    # Statystyki po ukończeniu eksportu (izolowane per-job)
    render_elapsed_s: float = 0.0
    average_fps: float = 0.0
    average_qp: Optional[float] = None
    codec: str = ""
    quant_metric: str = ""
    quant_avg: Optional[float] = None
    quant_min: Optional[int] = None
    quant_max: Optional[int] = None
    quant_samples: Optional[int] = None
    is_expanded: bool = False

    def __post_init__(self) -> None:
        self.video_paths = [str(p) for p in (self.video_paths or [])]
        if self.fit_path:
            self.fit_path = str(self.fit_path)
        if self.gpx_path:
            self.gpx_path = str(self.gpx_path)
        if self.output_path:
            self.output_path = str(self.output_path)
        if not self.telemetry_cache_key and self.video_paths:
            try:
                from src.telemetry_cache_manager import compute_source_key
                self.telemetry_cache_key = compute_source_key(self.video_paths[0])
            except Exception:
                pass

    def display_name(self) -> str:
        """Krótka nazwa do wyświetlenia w UI."""
        if self.video_paths:
            base = Path(self.video_paths[-1]).name
        else:
            base = "???"
        out = Path(self.output_path).name
        return f"{base} → {out}"

    def is_active(self) -> bool:
        return self.render_status in ("preparing", "running", "finalizing") or self.upload_status == "running"

    def is_done(self) -> bool:
        """True gdy render AND upload (jeśli włączony) zakończone."""
        r_ok = self.render_status in ("done", "error", "cancelled", "interrupted")
        if not r_ok:
            return False
        if self.yt_enabled:
            return self.upload_status in ("done", "error", "interrupted")
        return True


# ─────────────────────────────────────────────────────────────────────────────
# YouTubeUploader
# ─────────────────────────────────────────────────────────────────────────────

_YT_SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]
_YT_CHUNK_SIZE = 256 * 1024  # 256 KB


class YouTubeUploader:
    """Resumable upload pliku MP4 na YouTube.

    Wymaga:
        pip install google-api-python-client google-auth-oauthlib

    Credentiale:
        %APPDATA%\\BikeRideHUD\\youtube_client_secret.json
        %APPDATA%\\BikeRideHUD\\youtube_token.json  (generowany przy pierwszym uruchomieniu)
    """

    SECRET_FILE = "youtube_client_secret.json"
    TOKEN_FILE = "youtube_token.json"

    def __init__(self) -> None:
        self._appdata = _appdata_dir()

    def _check_deps(self) -> None:
        try:
            import googleapiclient  # noqa: F401
            import google_auth_oauthlib  # noqa: F401
        except ImportError as e:
            raise RuntimeError(
                "Brak bibliotek YouTube API. Zainstaluj:\n"
                "  pip install google-api-python-client google-auth-oauthlib\n"
                f"Szczegóły: {e}"
            ) from e

    def _build_service(self):
        """Zwraca autoryzowany zasób YouTube Data API v3."""
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
        from googleapiclient.discovery import build

        secret_path = self._appdata / self.SECRET_FILE
        token_path = self._appdata / self.TOKEN_FILE

        if not secret_path.exists():
            raise FileNotFoundError(
                f"Brak pliku client_secret: {secret_path}\n"
                "Pobierz go z Google Cloud Console i zapisz w:\n"
                f"  {self._appdata}"
            )

        creds = None
        if token_path.exists():
            creds = Credentials.from_authorized_user_file(str(token_path), _YT_SCOPES)

        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                flow = InstalledAppFlow.from_client_secrets_file(
                    str(secret_path), _YT_SCOPES
                )
                creds = flow.run_local_server(port=0)
            token_path.write_text(creds.to_json(), encoding="utf-8")

        return build("youtube", "v3", credentials=creds)

    def upload(
        self,
        file_path: str,
        title: str,
        description: str,
        privacy: str,
        on_progress: Optional[Callable[[float], None]] = None,
        cancel_event: Optional[threading.Event] = None,
    ) -> str:
        """Prześlij plik na YouTube. Zwraca video_id."""
        self._check_deps()
        from googleapiclient.http import MediaFileUpload

        service = self._build_service()
        media = MediaFileUpload(
            file_path,
            mimetype="video/mp4",
            resumable=True,
            chunksize=_YT_CHUNK_SIZE,
        )
        body = {
            "snippet": {
                "title": title or Path(file_path).stem,
                "description": description or "",
                "categoryId": "17",  # Sports
            },
            "status": {
                "privacyStatus": privacy or "private",
            },
        }
        request = service.videos().insert(
            part="snippet,status",
            body=body,
            media_body=media,
        )

        response = None
        while response is None:
            if cancel_event and cancel_event.is_set():
                raise InterruptedError("Upload anulowany")
            status, response = request.next_chunk()
            if status and on_progress:
                try:
                    on_progress(status.progress())
                except Exception:
                    pass

        video_id = response.get("id", "")
        log.info("[YT Upload] Done: video_id=%s", video_id)
        return video_id


# ─────────────────────────────────────────────────────────────────────────────
# ExportQueue
# ─────────────────────────────────────────────────────────────────────────────

QUEUE_FILE = "export_queue.json"
QUEUE_FORMAT_NAME = "BikeRideHUD Export Queue"
QUEUE_FORMAT_VERSION = 1

_RENDER_TERMINAL = {"done", "error", "cancelled", "interrupted"}
_UPLOAD_TERMINAL = {"idle", "done", "error", "interrupted"}  # idle = YT not enabled


class ExportQueue:
    """Kolejka eksportu z harmonogramem render/upload.

    Użycie:
        queue = ExportQueue(signals=get_signals())
        queue.set_render_callback(fn)   # fn(job) — uruchamia rendering
        queue.start()
        queue.add_job(job)
    """

    def __init__(self, signals=None, appdata_dir: Optional[Path] = None) -> None:
        self._signals = signals
        self._lock = threading.Lock()
        self._jobs: list[ExportJob] = []
        self._paused = True
        self._stopped = False
        self._render_cb: Optional[Callable[[ExportJob], None]] = None
        self._active_render_id: Optional[str] = None
        self._active_upload_id: Optional[str] = None
        self._scheduler_event = threading.Event()
        self._scheduler_thread: Optional[threading.Thread] = None
        self._on_job_updated_cb: Optional[Callable[[ExportJob], None]] = None
        self._cancel_upload_event = threading.Event()
        self._appdata = Path(appdata_dir) if appdata_dir is not None else _appdata_dir()
        self._queue_path = self._appdata / QUEUE_FILE
        self._load_persisted()

    # ── Public API ────────────────────────────────────────────────────────

    def set_render_callback(self, fn: Callable[[ExportJob], None]) -> None:
        """Callback wywoływany gdy scheduler chce uruchomić render jobu."""
        self._render_cb = fn

    def set_on_job_updated(self, fn: Callable[[ExportJob], None]) -> None:
        """Callback wywoływany po każdej zmianie stanu jobu (z wątku kolejki)."""
        self._on_job_updated_cb = fn

    def start(self) -> None:
        """Uruchom / wznów przetwarzanie kolejki."""
        with self._lock:
            if self._stopped:
                return
            self._paused = False
        log_queue_trace("QUEUE START", extra="queue_resumed=True")
        self._wake_scheduler()
        if self._scheduler_thread is None or not self._scheduler_thread.is_alive():
            self._scheduler_thread = threading.Thread(
                target=self._scheduler_loop,
                daemon=True,
                name="TeleM-ExportQueue",
            )
            self._scheduler_thread.start()
        sig = getattr(self._signals, "sig_queue_started", None)
        if sig:
            sig.emit()

    def pause(self) -> None:
        """Wstrzymaj — aktywny render dobiegnie końca, nowe nie startują."""
        with self._lock:
            self._paused = True
        sig = getattr(self._signals, "sig_queue_paused", None)
        if sig:
            sig.emit()

    def stop(self) -> None:
        """Zatrzymaj kolejkę (nie można wznowić bez nowego startu)."""
        with self._lock:
            self._stopped = True
            self._paused = True
        self._cancel_upload_event.set()
        self._wake_scheduler()

    def add_job(self, job: ExportJob) -> None:
        """Dodaj nowy job na koniec kolejki."""
        # Zabezpiecz ścieżkę wyjściową przed nadpisaniem
        job.output_path = _safe_output_path(job.output_path)
        with self._lock:
            self._jobs.append(job)
        self._persist()
        self._notify_updated(job)
        self._wake_scheduler()
        log.info("[Queue] add_job id=%s out=%s", job.job_id, job.output_path)

    def remove_job(self, job_id: str) -> bool:
        """Usuń job (tylko jeśli nie jest aktualnie renderowany)."""
        with self._lock:
            if job_id == self._active_render_id:
                log.warning("[Queue] remove_job: cannot remove active render %s", job_id)
                return False
            before = len(self._jobs)
            self._jobs = [j for j in self._jobs if j.job_id != job_id]
            removed = len(self._jobs) < before
        if removed:
            self._persist()
        return removed

    def get_jobs(self) -> list[ExportJob]:
        """Zwraca płytką kopię listy jobów (thread-safe)."""
        with self._lock:
            return list(self._jobs)

    def get_job(self, job_id: str) -> Optional[ExportJob]:
        """Znajdź job po ID (publiczny accessor)."""
        return self._find_job(job_id)

    def notify_render_started(self, job_id: str) -> None:
        """Wywołaj gdy worker renderujący faktycznie wystartował (stan: running/RENDERING)."""
        job = self._find_job(job_id)
        if job is None:
            return
        job.render_status = "running"
        log_queue_trace(
            "RENDER WORKER START",
            job_id=job.job_id,
            output_path=job.output_path,
            input_videos=job.video_paths,
            extra="status=running",
        )
        self._persist()
        self._notify_updated(job)

    def notify_render_done(
        self,
        job_id: str,
        *,
        success: bool,
        cancelled: bool = False,
        output_path: str = "",
        error_message: str = "",
        elapsed_s: float = 0.0,
        average_fps: float = 0.0,
        average_qp: float | None = None,
        codec: str = "",
        quant_metric: str = "",
        quant_avg: float | None = None,
        quant_min: int | None = None,
        quant_max: int | None = None,
        quant_samples: int | None = None,
    ) -> None:
        """Wywołaj po zakończeniu renderu (z wątku renderu lub GUI)."""
        job = self._find_job(job_id)
        if job is None:
            return
        with self._lock:
            already_done = job.render_status in ("done", "error", "cancelled")
            if not already_done:
                self._active_render_id = None

        # Always update per-job statistics if provided
        if elapsed_s > 0:
            job.render_elapsed_s = elapsed_s
        elif job.render_finished_at and job.render_started_at and not job.render_elapsed_s:
            job.render_elapsed_s = max(0.0, job.render_finished_at - job.render_started_at)
        if average_fps > 0:
            job.average_fps = average_fps
        if average_qp is not None:
            job.average_qp = average_qp
        if codec:
            job.codec = codec
        if quant_metric:
            job.quant_metric = quant_metric
        if quant_avg is not None:
            job.quant_avg = quant_avg
        if quant_min is not None:
            job.quant_min = quant_min
        if quant_max is not None:
            job.quant_max = quant_max
        if quant_samples is not None:
            job.quant_samples = quant_samples

        if already_done:
            # Already finalized state machine, but persist updated stats if any
            if elapsed_s > 0 or average_fps > 0 or average_qp is not None or quant_avg is not None:
                self._persist()
                self._notify_updated(job)
            return

        job.render_finished_at = time.time()
        if not job.render_elapsed_s and job.render_started_at:
            job.render_elapsed_s = max(0.0, job.render_finished_at - job.render_started_at)
        if success:
            job.render_status = "done"
            job.render_progress = 1.0
            if output_path:
                job.output_path = output_path
            if job.yt_enabled:
                job.upload_status = "waiting"
        elif cancelled:
            job.render_status = "cancelled"
            job.render_error = error_message or "Anulowano"
        else:
            job.render_status = "error"
            if error_message:
                job.render_error = error_message
        log_queue_trace(
            "RENDER DONE",
            job_id=job.job_id,
            output_path=job.output_path,
            input_videos=job.video_paths,
            extra=f"success={success} error={job.render_error} fps={job.average_fps:.1f} qp={job.average_qp} quant_avg={job.quant_avg} elapsed={job.render_elapsed_s:.1f}s",
        )
        self._persist()
        self._notify_updated(job)
        self._wake_scheduler()

    def notify_render_progress(self, job_id: str, progress: float, phase: str = "") -> None:
        """Aktualizuj postęp renderu (0..1) oraz opcjonalnie stan/fazę."""
        job = self._find_job(job_id)
        if job is None:
            return
        clamped = max(0.0, min(1.0, progress))
        prev_pct = int(job.render_progress * 100)
        curr_pct = int(clamped * 100)
        job.render_progress = clamped
        if phase in ("finalize", "finalizing"):
            job.render_status = "finalizing"
        elif phase in ("render", "running") and job.render_status in ("preparing", "error"):
            job.render_status = "running"
            if job.render_error == "Render worker did not start":
                job.render_error = ""
        elif clamped > 0.0 and job.render_status in ("preparing", "error"):
            job.render_status = "running"
            if job.render_error == "Render worker did not start":
                job.render_error = ""
        if curr_pct != prev_pct or (clamped > 0.0 and prev_pct == 0):
            log_queue_trace(
                "QUEUE PROGRESS",
                job_id=job.job_id,
                output_path=job.output_path,
                input_videos=job.video_paths,
                extra=f"pct={clamped * 100:.1f}% status={job.render_status}",
            )
        self._notify_updated(job)

    # ── Internal scheduler ────────────────────────────────────────────────

    def _scheduler_loop(self) -> None:
        log.info("[Queue] Scheduler started")
        while True:
            self._scheduler_event.wait(timeout=1.0)
            self._scheduler_event.clear()
            with self._lock:
                if self._stopped:
                    break
                paused = self._paused
                active_render = self._active_render_id

            if paused:
                continue

            # ── Watchdog startu (Section 6) ───────────────────────────────────
            # Jeśli aktywne zadanie jest w preparing lub running (0% progress)
            # dłużej niż watchdog_timeout (domyślnie 10 s) bez startu workera -> FAILED
            if active_render:
                job = self._find_job(active_render)
                if job and job.render_started_at:
                    elapsed = time.time() - job.render_started_at
                    watchdog_timeout = float(os.environ.get("TELEM_QUEUE_WATCHDOG_TIMEOUT", "10.0"))
                    if elapsed > watchdog_timeout and job.render_status == "preparing":
                        log.error("[Queue Watchdog] Render timed out after %.1fs: %s", elapsed, job.job_id)
                        log_queue_trace(
                            "QUEUE WATCHDOG TIMEOUT",
                            job_id=job.job_id,
                            output_path=job.output_path,
                            input_videos=job.video_paths,
                            extra=f"elapsed={elapsed:.1f}s error='Render worker did not start'",
                        )
                        job.render_status = "error"
                        job.render_error = "Render worker did not start"
                        with self._lock:
                            self._active_render_id = None
                        self._persist()
                        self._notify_updated(job)
                        self._wake_scheduler()

            self._try_start_render()
            self._try_start_upload()

        log.info("[Queue] Scheduler stopped")

    def _try_start_render(self) -> None:
        with self._lock:
            if self._active_render_id is not None:
                return  # render już trwa
            job = self._next_queued_render()
            if job is None:
                return
            # Section 5: stan QUEUED -> PREPARING (dopiero po potwierdzeniu workera running)
            job.render_status = "preparing"
            job.render_started_at = time.time()
            job.render_progress = 0.0
            job.render_error = ""
            self._active_render_id = job.job_id

        self._persist()
        self._notify_updated(job)
        log.info("[Queue] Pick job: %s", job.job_id)
        log_queue_trace(
            "QUEUE PICK JOB",
            job_id=job.job_id,
            output_path=job.output_path,
            input_videos=job.video_paths,
            extra=f"status={job.render_status}",
        )
        cb = self._render_cb
        if cb:
            try:
                cb(job)
            except Exception as exc:
                log.exception("[Queue] Render callback error: %s", exc)
                job.render_status = "error"
                job.render_error = str(exc)
                with self._lock:
                    self._active_render_id = None
                self._persist()
                self._notify_updated(job)
                self._wake_scheduler()

    def _try_start_upload(self) -> None:
        with self._lock:
            if self._active_upload_id is not None:
                return  # upload już trwa
            job = self._next_waiting_upload()
            if job is None:
                return
            job.upload_status = "running"
            job.upload_started_at = time.time()
            job.upload_progress = 0.0
            self._active_upload_id = job.job_id

        self._persist()
        self._notify_updated(job)
        log.info("[Queue] Start upload: %s", job.job_id)
        t = threading.Thread(
            target=self._upload_worker,
            args=(job,),
            daemon=True,
            name=f"TeleM-YTUpload-{job.job_id[:8]}",
        )
        t.start()

    def _upload_worker(self, job: ExportJob) -> None:
        self._cancel_upload_event.clear()
        uploader = YouTubeUploader()
        try:
            video_id = uploader.upload(
                file_path=job.output_path,
                title=job.yt_title or Path(job.output_path).stem,
                description=job.yt_description,
                privacy=job.yt_privacy,
                on_progress=lambda p: self._on_upload_progress(job, p),
                cancel_event=self._cancel_upload_event,
            )
            job.yt_video_id = video_id
            job.upload_status = "done"
            job.upload_finished_at = time.time()
        except InterruptedError:
            job.upload_status = "error"
            job.upload_error = "Anulowano upload"
        except Exception as exc:
            log.exception("[Queue] Upload error: %s", exc)
            job.upload_status = "error"
            job.upload_error = str(exc)
        finally:
            with self._lock:
                self._active_upload_id = None
        self._persist()
        self._notify_updated(job)
        self._wake_scheduler()

    def _on_upload_progress(self, job: ExportJob, progress: float) -> None:
        job.upload_progress = max(0.0, min(1.0, progress))
        self._notify_updated(job)

    def _next_queued_render(self) -> Optional[ExportJob]:
        """Zwraca pierwszy job z render_status=='queued' (wywołuj pod lockiem)."""
        for j in self._jobs:
            if j.render_status == "queued":
                return j
        return None

    def _next_waiting_upload(self) -> Optional[ExportJob]:
        """Zwraca pierwszy job z upload_status=='waiting' (wywołuj pod lockiem)."""
        for j in self._jobs:
            if j.upload_status == "waiting":
                return j
        return None

    def _find_job(self, job_id: str) -> Optional[ExportJob]:
        with self._lock:
            for j in self._jobs:
                if j.job_id == job_id:
                    return j
        return None

    def _wake_scheduler(self) -> None:
        self._scheduler_event.set()

    # ── Notifications ─────────────────────────────────────────────────────

    def _notify_updated(self, job: ExportJob) -> None:
        """Powiadom GUI o zmianie stanu jobu (thread-safe przez Qt sygnał)."""
        cb = self._on_job_updated_cb
        if cb:
            try:
                cb(job)
            except Exception:
                pass
        sig = getattr(self._signals, "sig_queue_job_updated", None)
        if sig:
            try:
                sig.emit(job)
            except Exception:
                pass

    # ── Job Control & Helpers ─────────────────────────────────────────────

    def get_active_render_id(self) -> Optional[str]:
        """Zwraca job_id aktualnie renderowanego zadania (lub None)."""
        with self._lock:
            return self._active_render_id

    def cancel_active_render(self, reason: str = "Anulowano (STOP)") -> bool:
        """Anuluj aktywne zadanie renderowania w kolejce."""
        with self._lock:
            active_id = self._active_render_id
            self._paused = True
        if not active_id:
            return False
        log_queue_trace("QUEUE ACTIVE CANCEL", job_id=active_id, extra=f"reason='{reason}'")
        self.notify_render_done(active_id, success=False, error_message=reason)
        return True

    def reorder_jobs(self, job_ids: list[str]) -> None:
        """Zmień kolejność zadań w kolejce wg podanej listy job_id."""
        with self._lock:
            job_map = {j.job_id: j for j in self._jobs}
            reordered = []
            for jid in job_ids:
                if jid in job_map:
                    reordered.append(job_map.pop(jid))
            # Dopisz pozostałe joby na koniec
            for remaining in job_map.values():
                reordered.append(remaining)
            self._jobs = reordered
        self._persist()
        self._wake_scheduler()

    # ── Persistence & Export / Import ─────────────────────────────────────

    def _persist(self) -> None:
        """Zapisz kolejkę do JSON (atomic replace z version=1)."""
        try:
            with self._lock:
                jobs_data = [asdict(j) for j in self._jobs]
            payload = {
                "format": QUEUE_FORMAT_NAME,
                "version": QUEUE_FORMAT_VERSION,
                "created_at": time.time(),
                "jobs": jobs_data,
            }
            tmp = self._queue_path.with_suffix(".tmp")
            tmp.parent.mkdir(parents=True, exist_ok=True)
            tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
            os.replace(tmp, self._queue_path)
        except Exception as exc:
            log.warning("[Queue] persist error: %s", exc)

    def _load_persisted(self) -> None:
        """Wczytaj kolejkę z pliku JSON (przy starcie aplikacji)."""
        if not self._queue_path.exists():
            return
        try:
            raw = json.loads(self._queue_path.read_text(encoding="utf-8"))
            migrated = False
            if isinstance(raw, list):
                raw_jobs = raw
                migrated = True
            elif isinstance(raw, dict):
                raw_jobs = raw.get("jobs", [])
            else:
                raw_jobs = []

            jobs = []
            for d in raw_jobs:
                # Statusy po crash / restart:
                # running / preparing -> interrupted
                if d.get("render_status") in ("running", "preparing"):
                    d["render_status"] = "interrupted"
                    d["render_error"] = d.get("render_error") or "Przerwano (restart aplikacji)"
                    d["render_progress"] = 0.0
                if d.get("upload_status") == "running":
                    d["upload_status"] = "interrupted"
                    d["upload_error"] = d.get("upload_error") or "Przerwano upload (restart aplikacji)"
                    d["upload_progress"] = 0.0
                valid_keys = {f.name for f in ExportJob.__dataclass_fields__.values()}
                filtered = {k: v for k, v in d.items() if k in valid_keys}
                jobs.append(ExportJob(**filtered))
            with self._lock:
                self._jobs = jobs
            log.info("[Queue] Loaded %d jobs from %s", len(jobs), self._queue_path)
            if migrated:
                self._persist()
        except Exception as exc:
            log.warning("[Queue] load_persisted error: %s", exc)

    def export_to_file(self, filepath: Path) -> None:
        """Eksportuj kolejkę do pliku *.telemqueue.json (BEZ sekretów ani tokenów)."""
        p = Path(filepath)
        p.parent.mkdir(parents=True, exist_ok=True)
        with self._lock:
            jobs_data = []
            for j in self._jobs:
                d = asdict(j)
                # Upewnij się, że nie ma żadnych tokenów (TOKENS_EXPORTED=False)
                d.pop("token", None)
                d.pop("access_token", None)
                d.pop("refresh_token", None)
                d.pop("client_secret", None)
                jobs_data.append(d)
        payload = {
            "format": QUEUE_FORMAT_NAME,
            "version": QUEUE_FORMAT_VERSION,
            "exported_at": time.time(),
            "jobs": jobs_data,
        }
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
        os.replace(tmp, p)

    def import_from_file(self, filepath: Path, mode: str = "append") -> int:
        """Importuj kolejkę z pliku *.telemqueue.json."""
        p = Path(filepath)
        if not p.is_file():
            raise FileNotFoundError(f"Plik kolejki nie istnieje: {p}")
        raw = json.loads(p.read_text(encoding="utf-8"))
        if isinstance(raw, list):
            raw_jobs = raw
        elif isinstance(raw, dict):
            raw_jobs = raw.get("jobs", [])
        else:
            raise ValueError(f"Nieprawidłowy format pliku kolejki: {p}")

        valid_keys = {f.name for f in ExportJob.__dataclass_fields__.values()}
        imported_jobs = []
        with self._lock:
            existing_ids = {j.job_id for j in self._jobs}

        for d in raw_jobs:
            filtered = {k: v for k, v in d.items() if k in valid_keys}
            job = ExportJob(**filtered)
            # Unikaj kolizji ID
            if not job.job_id or job.job_id in existing_ids:
                job.job_id = str(uuid.uuid4())
            existing_ids.add(job.job_id)

            # Sprawdź dostępność plików wideo — nie crashuj przy brakujących
            missing = []
            for vp in job.video_paths:
                if not Path(vp).exists():
                    missing.append(Path(vp).name)
            if missing:
                job.render_status = "error"
                job.render_error = f"Brakujące pliki źródłowe: {', '.join(missing)}"
            imported_jobs.append(job)

        with self._lock:
            if mode == "replace":
                self._jobs = imported_jobs
            else:
                self._jobs.extend(imported_jobs)

        self._persist()
        for j in imported_jobs:
            self._notify_updated(j)
        self._wake_scheduler()
        return len(imported_jobs)
