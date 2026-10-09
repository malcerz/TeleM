"""Render Error Framework — centralna taksonomia błędów renderowania, preflight,
kontrolowana finalizacja i ochrona przed awarią aplikacji.

NAJWAŻNIEJSZY INVARIANT:
BŁĄD POJEDYNCZEGO RENDERU NIGDY NIE MOŻE WYWRÓCIĆ APLIKACJI GUI.
Render jest zadaniem (Job). Job może zakończyć się statusem:
  - DONE
  - PARTIAL
  - ERROR
  - CANCELLED
Kolejka (Queue) w przypadku błędów globalnych (brak miejsca, awaria GPU) jest
wstrzymywana (PAUSED), a błędy lokalne dla danego zadania (np. brak pliku)
nie zatrzymują pozostałych poprawnych zadań.
"""

from __future__ import annotations

import enum
import json
import logging
import os
import shutil
import subprocess
import threading
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional, Union

log = logging.getLogger(__name__)

# Stała domyślna rezerwy finalizacji: 512 MB (lub dynamicznie 5% szacowanego pliku)
DEFAULT_FINALIZATION_RESERVE_BYTES = 512 * 1024 * 1024


class ErrorScope(str, enum.Enum):
    """Zasięg błędu renderowania decydujący o zachowaniu kolejki."""
    JOB_ONLY = "JOB_ONLY"              # Błąd dotyczy wyłącznie danego zadania (np. brakujący klip)
    QUEUE_BLOCKER = "QUEUE_BLOCKER"    # Błąd blokuje całą kolejkę (np. brak miejsca na dysku)
    GLOBAL_BACKEND = "GLOBAL_BACKEND"  # Awaria globalna podsystemu (np. awaria GPU/sterownika)


@dataclass
class RenderError(RuntimeError):
    """Bazowa struktura i klasa błędu renderowania zgodna z protokołem IPC."""
    code: str = "RENDER_ERROR"
    category: str = "general"
    user_message: str = "Wystąpił błąd podczas eksportu."
    technical_message: str = ""
    job_id: str = ""
    backend: str = ""
    codec: str = ""
    frame: Optional[int] = None
    clip: str = ""
    recoverable: bool = False
    pause_queue: bool = False
    partial_output_possible: bool = False
    partial_output_valid: bool = False
    scope: str = ErrorScope.JOB_ONLY.value
    hresult: Optional[int] = None
    win32_error: Optional[int] = None
    ffmpeg_return_code: Optional[int] = None
    stderr_tail: str = ""
    device_removed_reason: Optional[int] = None
    details: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.technical_message:
            self.technical_message = self.user_message
        super().__init__(f"[{self.code}] {self.user_message} (Details: {self.technical_message})")

    def __str__(self) -> str:
        return f"[{self.code}] Insufficient disk space / {self.user_message} (Details: {self.technical_message})" if self.category == "storage" else f"[{self.code}] {self.user_message} (Details: {self.technical_message})"

    def to_dict(self) -> dict[str, Any]:
        """Konwertuje błąd do postaci słownika JSON-serializable dla IPC."""
        d = asdict(self)
        d["type"] = "render_error"
        d["exception_class"] = self.__class__.__name__
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RenderError":
        """Rekonstruuje obiekt błędu z payloadu IPC zachowując odpowiednią klasę."""
        exc_cls_name = data.get("exception_class") or data.get("type")
        target_cls = ERROR_CLASS_MAP.get(exc_cls_name, RenderError)
        
        # Filtrujemy tylko znane pola dataclass
        field_names = {f.name for f in cls.__dataclass_fields__.values()}
        kwargs = {k: v for k, v in data.items() if k in field_names}
        return target_cls(**kwargs)

    def __str__(self) -> str:
        res = f"[{self.code}] {self.user_message}"
        if self.technical_message and self.technical_message != self.user_message:
            res += f" (Szczegóły: {self.technical_message})"
        return res


# Specjalistyczne podklasy błędów
class PreflightError(RenderError):
    def __init__(self, **kwargs: Any) -> None:
        kwargs.setdefault("category", "preflight")
        kwargs.setdefault("code", "PREFLIGHT_FAIL")
        super().__init__(**kwargs)

def resolve_project_duration_s(
    cached_duration_s: float,
    video_timeline: Any = None,
    video_paths: list = None
) -> float:
    """Rozwiązuje kanoniczną długość projektu. Rzuca PreflightError jeśli się nie uda."""
    
    # 1. Sprawdź jawnie przekazany cached duration
    if cached_duration_s > 0.0:
        return float(cached_duration_s)

    # 2. Sprawdź video_timeline
    if video_timeline is not None:
        dur = getattr(video_timeline, "project_duration_s", 0.0)
        if dur > 0.0:
            return float(dur)

    # 3. Zbuduj tymczasowy timeline z klipów, jeśli podano ścieżki
    if video_paths:
        try:
            from src.multifile import build_timeline_from_paths
            temp_timeline = build_timeline_from_paths([Path(p) for p in video_paths])
            dur = getattr(temp_timeline, "project_duration_s", 0.0)
            if dur > 0.0:
                return float(dur)
        except Exception as e:
            raise PreflightError(
                category="preflight",
                user_message=f"Nie można ustalić długości wideo z plików źródłowych:\n{e}"
            )

    # 4. Nadal <= 0
    raise PreflightError(
        category="preflight",
        user_message="Nie można ustalić długości eksportowanego materiału.\nSpróbuj ponownie wczytać projekt lub plik wideo."
    )



class StorageError(RenderError):
    def __init__(self, **kwargs: Any) -> None:
        kwargs.setdefault("category", "storage")
        kwargs.setdefault("code", "STORAGE_ERROR")
        kwargs.setdefault("pause_queue", True)
        kwargs.setdefault("scope", ErrorScope.QUEUE_BLOCKER.value)
        super().__init__(**kwargs)


class SourceReadError(RenderError):
    def __init__(self, **kwargs: Any) -> None:
        kwargs.setdefault("category", "source")
        kwargs.setdefault("code", "SOURCE_READ_ERROR")
        kwargs.setdefault("scope", ErrorScope.JOB_ONLY.value)
        super().__init__(**kwargs)


class DecoderError(RenderError):
    def __init__(self, **kwargs: Any) -> None:
        kwargs.setdefault("category", "decode")
        kwargs.setdefault("code", "DECODER_ERROR")
        kwargs.setdefault("scope", ErrorScope.JOB_ONLY.value)
        super().__init__(**kwargs)


class GpuError(RenderError):
    def __init__(self, **kwargs: Any) -> None:
        kwargs.setdefault("category", "gpu")
        kwargs.setdefault("code", "GPU_DEVICE_ERROR")
        kwargs.setdefault("pause_queue", True)
        kwargs.setdefault("scope", ErrorScope.GLOBAL_BACKEND.value)
        super().__init__(**kwargs)


class EncoderError(RenderError):
    def __init__(self, **kwargs: Any) -> None:
        kwargs.setdefault("category", "encoder")
        kwargs.setdefault("code", "ENCODER_ERROR")
        super().__init__(**kwargs)


class MuxError(RenderError):
    def __init__(self, **kwargs: Any) -> None:
        kwargs.setdefault("category", "mux")
        kwargs.setdefault("code", "MUX_ERROR")
        super().__init__(**kwargs)


class AudioError(RenderError):
    def __init__(self, **kwargs: Any) -> None:
        kwargs.setdefault("category", "audio")
        kwargs.setdefault("code", "AUDIO_ERROR")
        kwargs.setdefault("scope", ErrorScope.JOB_ONLY.value)
        super().__init__(**kwargs)


class TelemetryError(RenderError):
    def __init__(self, **kwargs: Any) -> None:
        kwargs.setdefault("category", "telemetry")
        kwargs.setdefault("code", "TELEMETRY_ERROR")
        kwargs.setdefault("scope", ErrorScope.JOB_ONLY.value)
        super().__init__(**kwargs)


class ChildProcessError(RenderError):
    def __init__(self, **kwargs: Any) -> None:
        kwargs.setdefault("category", "child_process")
        kwargs.setdefault("code", "CHILD_CRASH")
        super().__init__(**kwargs)


class ResourceError(RenderError):
    def __init__(self, **kwargs: Any) -> None:
        kwargs.setdefault("category", "resource")
        kwargs.setdefault("code", "OUT_OF_MEMORY")
        kwargs.setdefault("pause_queue", True)
        kwargs.setdefault("scope", ErrorScope.QUEUE_BLOCKER.value)
        super().__init__(**kwargs)


class RenderCancelled(Exception):
    """Jawne, kontrolowane anulowanie renderowania (nie jest błędem)."""
    def __init__(self, reason: str = "Anulowano przez użytkownika") -> None:
        super().__init__(reason)
        self.reason = reason


ERROR_CLASS_MAP: dict[str, type[RenderError]] = {
    "RenderError": RenderError,
    "PreflightError": PreflightError,
    "StorageError": StorageError,
    "SourceReadError": SourceReadError,
    "DecoderError": DecoderError,
    "GpuError": GpuError,
    "EncoderError": EncoderError,
    "MuxError": MuxError,
    "AudioError": AudioError,
    "TelemetryError": TelemetryError,
    "ChildProcessError": ChildProcessError,
    "ResourceError": ResourceError,
}


# ─────────────────────────────────────────────────────────────────────────────
# Estymacja i Preflight miejsca na dysku (Storage Preflight)
# ─────────────────────────────────────────────────────────────────────────────

def parse_bitrate_to_bps(bitrate_val: Union[str, int, float, None], default_bps: int = 40_000_000) -> int:
    """Konwertuje wartość bitrate (np. '40M', '40Mbps', '25000k', 50000000) na bity/s."""
    if not bitrate_val:
        return default_bps
    if isinstance(bitrate_val, (int, float)):
        return int(bitrate_val)
    val_str = str(bitrate_val).strip().lower()
    try:
        if val_str.endswith("mbps"):
            return int(float(val_str[:-4]) * 1_000_000)
        if val_str.endswith("m"):
            return int(float(val_str[:-1]) * 1_000_000)
        if val_str.endswith("kbps"):
            return int(float(val_str[:-4]) * 1_000)
        if val_str.endswith("k"):
            return int(float(val_str[:-1]) * 1_000)
        return int(float(val_str))
    except (ValueError, TypeError):
        return default_bps


def estimate_required_export_space(
    duration_s: float,
    video_bitrate_bps: int,
    codec: str = "hevc",
    has_audio: bool = True,
    is_vbr: bool = True,
) -> tuple[int, int]:
    """Oblicza szacowane wymagane miejsce na dysku oraz rezerwę finalizacji.
    
    Wzór:
      video_bytes = (video_bitrate_bps / 8) * duration_s
      audio_bytes = (audio_bitrate_bps / 8) * duration_s (domyślnie ~384 kbps)
      safety_margin: 20% dla CBR, 30% dla VBR/Quality
      finalization_reserve: max(512 MB, 5% szacowanego rozmiaru)
      
    Zwraca: (required_bytes_with_margin, finalization_reserve_bytes)
    """
    eff_dur = max(0.5, float(duration_s))
    video_bytes = (float(video_bitrate_bps) / 8.0) * eff_dur
    audio_bitrate_bps = 384_000 if has_audio else 0
    audio_bytes = (float(audio_bitrate_bps) / 8.0) * eff_dur
    base_file_bytes = video_bytes + audio_bytes

    margin_factor = 1.30 if is_vbr else 1.20
    finalization_reserve = max(
        DEFAULT_FINALIZATION_RESERVE_BYTES,
        int(base_file_bytes * 0.05),
    )
    total_required = int(base_file_bytes * margin_factor) + finalization_reserve
    return total_required, finalization_reserve


def check_preflight_storage(
    output_path: Union[str, Path],
    duration_s: float,
    video_bitrate_bps: int,
    codec: str = "hevc",
    has_audio: bool = True,
    is_vbr: bool = True,
) -> tuple[bool, Optional[StorageError]]:
    """Sprawdza czy docelowy nośnik posiada wystarczającą ilość wolnego miejsca.
    
    Jeśli brakuje miejsca lub folder jest niedostępny, zwraca (False, StorageError).
    W przeciwnym wypadku zwraca (True, None).
    """
    out_p = Path(output_path).resolve()
    target_dir = out_p.parent

    # Upewnij się, że katalog istnieje lub można go utworzyć
    try:
        target_dir.mkdir(parents=True, exist_ok=True)
    except Exception as exc:
        err = StorageError(
            code="DIR_CREATE_FAILED",
            user_message=f"Nie można utworzyć katalogu docelowego:\n{target_dir}",
            technical_message=f"mkdir failed for {target_dir}: {exc}",
            scope=ErrorScope.QUEUE_BLOCKER.value,
        )
        return False, err

    # Sprawdzenie uprawnień do zapisu
    try:
        test_file = target_dir / f".telem_perm_test_{os.getpid()}_{int(time.time()*1000)}"
        test_file.write_bytes(b"ok")
        if test_file.exists():
            test_file.unlink()
    except Exception as exc:
        err = StorageError(
            code="DIR_NOT_WRITABLE",
            user_message=f"Brak uprawnień do zapisu w folderze:\n{target_dir}",
            technical_message=f"Permission test failed on {target_dir}: {exc}",
            scope=ErrorScope.QUEUE_BLOCKER.value,
        )
        return False, err

    # Sprawdzenie wolnego miejsca
    try:
        usage = shutil.disk_usage(str(target_dir))
    except Exception as exc:
        err = StorageError(
            code="DISK_QUERY_FAILED",
            user_message=f"Nie można odczytać stanu dysku docelowego:\n{target_dir}",
            technical_message=f"disk_usage failed for {target_dir}: {exc}",
            scope=ErrorScope.QUEUE_BLOCKER.value,
        )
        return False, err

    req_bytes, fin_reserve = estimate_required_export_space(
        duration_s=duration_s,
        video_bitrate_bps=video_bitrate_bps,
        codec=codec,
        has_audio=has_audio,
        is_vbr=is_vbr,
    )

    free_bytes = usage.free
    if free_bytes < req_bytes:
        drive_name = target_dir.drive or str(target_dir)
        free_gb = free_bytes / (1024 ** 3)
        req_gb = req_bytes / (1024 ** 3)
        msg_user = (
            f"Za mało miejsca na dysku {drive_name}.\n\n"
            f"Wymagane z zapasem: {req_gb:.1f} GB\n"
            f"Dostępne: {free_gb:.1f} GB\n\n"
            f"Zwolnij miejsce na dysku lub wybierz inny folder docelowy."
        )
        msg_tech = (
            f"ENOSPC preflight: free={free_bytes} B ({free_gb:.2f} GB) < "
            f"required={req_bytes} B ({req_gb:.2f} GB) on {target_dir}"
        )
        err = StorageError(
            code="ENOSPC_PREFLIGHT",
            user_message=msg_user,
            technical_message=f"ENOSPC_PREFLIGHT_FAIL: Insufficient disk space. {msg_tech}",
            pause_queue=True,
            scope=ErrorScope.QUEUE_BLOCKER.value,
            details={
                "free_bytes": free_bytes,
                "required_bytes": req_bytes,
                "finalization_reserve": fin_reserve,
                "target_dir": str(target_dir),
            },
        )
        return False, err

    return True, None


def check_preflight_sources(video_paths: list[Union[str, Path]]) -> tuple[bool, Optional[SourceReadError]]:
    """Sprawdza obecność i dostępność wszystkich plików źródłowych klipów."""
    if not video_paths:
        return False, SourceReadError(
            code="NO_SOURCES",
            user_message="Brak plików wideo do wyrenderowania.",
            technical_message="video_paths list is empty",
        )
    for p_str in video_paths:
        p = Path(p_str)
        if not p.exists():
            return False, SourceReadError(
                code="SOURCE_MISSING",
                user_message=f"Plik wideo nie istnieje:\n{p.name}",
                technical_message=f"Source clip not found: {p}",
                clip=str(p),
            )
        if not p.is_file():
            return False, SourceReadError(
                code="SOURCE_NOT_A_FILE",
                user_message=f"Ścieżka źródłowa nie jest plikiem:\n{p.name}",
                technical_message=f"Source clip path is not a file: {p}",
                clip=str(p),
            )
        try:
            with open(p, "rb") as f:
                f.read(1024)
        except Exception as exc:
            return False, SourceReadError(
                code="SOURCE_UNREADABLE",
                user_message=f"Brak możliwości odczytu pliku źródłowego:\n{p.name}",
                technical_message=f"Failed to read source clip {p}: {exc}",
                clip=str(p),
            )
    return True, None


# ─────────────────────────────────────────────────────────────────────────────
# Runtime Storage Monitor (Kontrola wolnego miejsca podczas renderowania)
# ─────────────────────────────────────────────────────────────────────────────

class RuntimeStorageMonitor:
    """Lekki wątek sprawdzający wolne miejsce na dysku co 1.5–2.0 s.
    
    W przypadku spadku wolnego miejsca poniżej progu finalization_reserve_bytes,
    ustawia zdarzenie stop_requested_low_space, umożliwiając pipeline'owi
    przerwanie podawania nowych klatek, normalny drain i poprawną finalizację MP4.
    """

    def __init__(
        self,
        target_path: Union[str, Path],
        finalization_reserve_bytes: int = DEFAULT_FINALIZATION_RESERVE_BYTES,
        poll_interval_s: float = 1.5,
        on_low_space_callback: Optional[Callable[[int, int], None]] = None,
    ) -> None:
        self.target_path = Path(target_path).resolve()
        self.target_dir = self.target_path.parent
        self.finalization_reserve_bytes = max(100 * 1024 * 1024, int(finalization_reserve_bytes))
        self.poll_interval_s = max(0.5, float(poll_interval_s))
        self.on_low_space_callback = on_low_space_callback

        self.stop_requested_low_space = threading.Event()
        self._thread_stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self.last_free_bytes: int = -1
        self.last_query_time: float = 0.0

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._thread_stop_event.clear()
        self._thread = threading.Thread(
            target=self._monitor_loop,
            daemon=True,
            name=f"TeleM-StorageMonitor-{os.getpid()}",
        )
        self._thread.start()

    def stop(self) -> None:
        self._thread_stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)
        self._thread = None

    def _monitor_loop(self) -> None:
        while not self._thread_stop_event.is_set():
            try:
                if self.target_dir.exists():
                    usage = shutil.disk_usage(str(self.target_dir))
                    self.last_free_bytes = usage.free
                    self.last_query_time = time.monotonic()

                    if usage.free <= self.finalization_reserve_bytes:
                        log.warning(
                            "[STORAGE MONITOR] LOW SPACE DETECTED: free=%d B <= reserve=%d B on %s",
                            usage.free,
                            self.finalization_reserve_bytes,
                            self.target_dir,
                        )
                        self.stop_requested_low_space.set()
                        if self.on_low_space_callback:
                            try:
                                self.on_low_space_callback(usage.free, self.finalization_reserve_bytes)
                            except Exception as cb_err:
                                log.error("[STORAGE MONITOR] Callback error: %s", cb_err)
                        break
            except Exception as exc:
                # W przypadku odłączenia nośnika/awarii dysku
                log.error("[STORAGE MONITOR] Query error: %s", exc)
                self.stop_requested_low_space.set()
                break

            self._thread_stop_event.wait(self.poll_interval_s)


# ─────────────────────────────────────────────────────────────────────────────
# Klasyfikator błędów FFmpeg i Muxera
# ─────────────────────────────────────────────────────────────────────────────

def classify_mux_error(
    returncode: Optional[int],
    stderr_tail: str = "",
    frame_idx: Optional[int] = None,
    job_id: str = "",
    backend: str = "",
) -> RenderError:
    """Analizuje kod zakończenia FFmpeg oraz treść stderr i zwraca właściwy błąd RenderError."""
    low_stderr = stderr_tail.lower()

    # 1. Sprawdzenie braku miejsca na dysku (ENOSPC / rc=-28)
    if (
        returncode == -28
        or returncode == 28
        or "no space left on device" in low_stderr
        or "averror(enospc)" in low_stderr
        or "error writing trailer: no space" in low_stderr
    ):
        return StorageError(
            code="ENOSPC",
            user_message="Brak miejsca na dysku przerwał zapis pliku wideo.",
            technical_message=f"FFmpeg ENOSPC (-28): {stderr_tail[-300:].strip() if stderr_tail else 'no space'}",
            frame=frame_idx,
            job_id=job_id,
            backend=backend,
            ffmpeg_return_code=returncode,
            stderr_tail=stderr_tail,
            pause_queue=True,
            recoverable=True,
            partial_output_possible=True,
        )

    # 2. Brak uprawnień do zapisu
    if "permission denied" in low_stderr:
        return StorageError(
            code="PERMISSION_DENIED",
            user_message="Brak uprawnień do zapisu w lokalizacji docelowej.",
            technical_message=f"FFmpeg permission denied: {stderr_tail[-300:].strip()}",
            frame=frame_idx,
            job_id=job_id,
            backend=backend,
            ffmpeg_return_code=returncode,
            stderr_tail=stderr_tail,
            pause_queue=True,
        )

    # 3. Odłączony lub niedostępny nośnik
    if "device not ready" in low_stderr or "no such device" in low_stderr or "device or resource busy" in low_stderr:
        return StorageError(
            code="DEVICE_UNAVAILABLE",
            user_message="Dysk docelowy został odłączony lub jest niedostępny.",
            technical_message=f"FFmpeg device error: {stderr_tail[-300:].strip()}",
            frame=frame_idx,
            job_id=job_id,
            backend=backend,
            ffmpeg_return_code=returncode,
            stderr_tail=stderr_tail,
            pause_queue=True,
        )

    # 4. Standardowy Broken Pipe w potoku
    if "broken pipe" in low_stderr:
        return MuxError(
            code="BROKEN_PIPE",
            user_message="Połączenie z procesem kodowania/muksowania zostało przerwane (Broken pipe).",
            technical_message=f"FFmpeg pipe broken: {stderr_tail[-300:].strip()}",
            frame=frame_idx,
            job_id=job_id,
            backend=backend,
            ffmpeg_return_code=returncode,
            stderr_tail=stderr_tail,
        )

    # 5. Domyślny błąd procesu FFmpeg
    return MuxError(
        code=f"FFMPEG_EXIT_{returncode}",
        user_message=f"Proces zapisu wideo zakończył się błędem (kod {returncode}).",
        technical_message=f"FFmpeg exited with rc={returncode}. Stderr: {stderr_tail[-400:].strip() if stderr_tail else 'none'}",
        frame=frame_idx,
        job_id=job_id,
        backend=backend,
        ffmpeg_return_code=returncode,
        stderr_tail=stderr_tail,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Walidacja pliku częściowego (Partial Output Validation via ffprobe)
# ─────────────────────────────────────────────────────────────────────────────

def validate_partial_output(
    ffprobe_exe: Union[str, Path],
    file_path: Union[str, Path],
    min_duration_s: float = 0.5,
) -> tuple[bool, float, dict[str, Any]]:
    """Weryfikuje poprawność kontenera i strumieni w pliku częściowym przy użyciu ffprobe.
    
    Zwraca: (is_valid, duration_s, stream_info_dict)
    """
    path = Path(file_path).resolve()
    if not path.exists() or path.stat().st_size <= 0:
        return False, 0.0, {"error": "file_not_found_or_empty"}

    cmd = [
        str(ffprobe_exe),
        "-v", "error",
        "-show_entries", "format=duration,size:stream=codec_type,codec_name,width,height",
        "-of", "json",
        str(path),
    ]

    try:
        proc = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=10.0,
        )
        if proc.returncode != 0:
            return False, 0.0, {"error": "ffprobe_failed", "stderr": proc.stderr}

        data = json.loads(proc.stdout)
        fmt = data.get("format", {})
        streams = data.get("streams", [])

        dur_str = fmt.get("duration")
        duration = float(dur_str) if dur_str is not None else 0.0

        has_video = any(s.get("codec_type") == "video" for s in streams)
        has_audio = any(s.get("codec_type") == "audio" for s in streams)

        is_valid = has_video and (duration >= min_duration_s)
        return is_valid, duration, {
            "duration": duration,
            "has_video": has_video,
            "has_audio": has_audio,
            "streams_count": len(streams),
            "size_bytes": path.stat().st_size,
        }
    except Exception as exc:
        return False, 0.0, {"error": str(exc)}
