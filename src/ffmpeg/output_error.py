"""Backward compatibility shim for output_error.py -> render_errors.py."""
from enum import Enum
from src.ffmpeg.render_errors import (
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
    def __init__(self, message: str, **kwargs):
        os_error = kwargs.get("os_error", "").lower()
        if "no space" in os_error:
            code = "ENOSPC"
        elif "permission" in os_error:
            code = "EACCES"
        elif "device" in os_error or "not ready" in os_error:
            code = "ENOENT"
        elif "broken pipe" in os_error:
            code = "EPIPE"
        else:
            code = "STORAGE_ERROR"
        
        kwargs.pop("output_path", None)
        kwargs.pop("os_error", None)
        super().__init__(user_message=message, code=code, **kwargs)
        self.category = "storage"

ExportOutputError = OutputWriteError

def classify_output_error(output_path: str, ffmpeg_return_code: int = 0, os_error: str = "") -> tuple[str, str]:
    err = os_error.lower()
    if "no space" in err:
        return "ENOSPC", "Brak miejsca na dysku"
    elif "permission" in err:
        return "EACCES", "Brak uprawnień do zapisu"
    elif "device" in err or "not ready" in err:
        return "ENOENT", "Urządzenie niedostępne"
    elif "broken pipe" in err:
        return "EPIPE", "Zapis przerwany (Broken pipe)"
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
