"""Backward compatibility shim for output_error.py -> render_errors.py."""
from enum import Enum
from src.ffmpeg.render_errors import (
    ERROR_CLASS_MAP,
    RenderError,
    StorageError,
    PreflightError,
    SourceReadError,
    DecoderError,
    GpuError,
    EncoderError,
    MuxError,
    AudioError,
    TelemetryError,
    ChildProcessError,
    ResourceError,
    RenderCancelled,
    ErrorScope,
    check_preflight_storage,
    check_preflight_sources,
    estimate_required_export_space,
    parse_bitrate_to_bps,
    classify_mux_error,
    validate_partial_output,
    RuntimeStorageMonitor,
)


class OutputWriteError(StorageError):
    def __init__(self, message: str = "", **kwargs):
        message = message or str(kwargs.get("user_message", "Błąd zapisu pliku wyjściowego."))
        os_error = kwargs.pop("os_error", "")
        output_path = str(kwargs.pop("output_path", "") or "")
        err_text = str(os_error).lower()
        err_number = getattr(os_error, "errno", None)
        if err_number == 28 or "no space" in err_text or "enospc" in err_text:
            code = "ENOSPC"
        elif err_number in (13, 1) or "permission" in err_text or "access is denied" in err_text:
            code = "EACCES"
        elif err_number in (19, 5) or "device" in err_text or "not ready" in err_text:
            code = "DEVICE_UNAVAILABLE"
        elif err_number == 32 or "broken pipe" in err_text or "epipe" in err_text:
            code = "EPIPE"
        elif err_number == 2 or "no such file" in err_text:
            code = "ENOENT"
        else:
            code = "STORAGE_ERROR"
        kwargs.setdefault("output_path", output_path)
        kwargs.setdefault("user_message", message)
        kwargs.setdefault("code", code)
        kwargs.setdefault("partial_output_possible", True)
        super().__init__(**kwargs)
        self.category = "storage"


ERROR_CLASS_MAP["OutputWriteError"] = OutputWriteError

ExportOutputError = OutputWriteError

def classify_output_error(output_path: str, ffmpeg_return_code: int = 0, os_error: str = "") -> tuple[str, str]:
    err = os_error.lower()
    if "no space" in err or "enospc" in err:
        return "ENOSPC", "Brak miejsca na dysku"
    elif "permission" in err or "access is denied" in err or "eacces" in err:
        return "EACCES", "Brak uprawnień do zapisu"
    elif "device" in err or "not ready" in err or "device_unavailable" in err:
        return "DEVICE_UNAVAILABLE", "Urządzenie niedostępne"
    elif "broken pipe" in err or "epipe" in err:
        return "EPIPE", "Zapis przerwany (Broken pipe)"
    elif "no such file" in err or "enoent" in err:
        return "ENOENT", "Nie znaleziono pliku lub katalogu"
    elif ffmpeg_return_code != 0:
        return "MUX_ERROR", "Błąd muxera"
    return "UNKNOWN", "Nieznany błąd zapisu"

__all__ = [
    "RenderError", "StorageError", "PreflightError", "SourceReadError",
    "DecoderError", "GpuError", "EncoderError", "MuxError", "AudioError",
    "TelemetryError", "ChildProcessError", "ResourceError", "RenderCancelled",
    "ErrorScope", "ExportOutputError", "OutputWriteError",
    "classify_output_error", "check_preflight_storage", "check_preflight_sources",
    "estimate_required_export_space", "parse_bitrate_to_bps", "classify_mux_error",
    "validate_partial_output", "RuntimeStorageMonitor"
]
