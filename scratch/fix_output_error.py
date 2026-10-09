import os
with open('src/ffmpeg/output_error.py', 'w', encoding='utf-8') as f:
    f.write('''"""Backward compatibility shim for output_error.py -> render_errors.py."""
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

class ExportOutputCategory(Enum):
    DISK_FULL = "ENOSPC"
    PERMISSION_DENIED = "EACCES"
    DEVICE_UNAVAILABLE = "ENOENT"
    BROKEN_PIPE = "EPIPE"
    MUX_FAILURE = "MUX_ERROR"
    UNKNOWN = "UNKNOWN"

class OutputWriteError(StorageError):
    def __init__(self, message: str, **kwargs):
        os_error = kwargs.get("os_error", "").lower()
        if "no space" in os_error:
            self.category = ExportOutputCategory.DISK_FULL
            code = "ENOSPC"
        elif "permission" in os_error:
            self.category = ExportOutputCategory.PERMISSION_DENIED
            code = "EACCES"
        elif "device" in os_error or "not ready" in os_error:
            self.category = ExportOutputCategory.DEVICE_UNAVAILABLE
            code = "ENOENT"
        elif "broken pipe" in os_error:
            self.category = ExportOutputCategory.BROKEN_PIPE
            code = "EPIPE"
        else:
            self.category = ExportOutputCategory.UNKNOWN
            code = "STORAGE_ERROR"
        
        super().__init__(user_message=message, code=code, **kwargs)

ExportOutputError = OutputWriteError

def classify_output_error(output_path: str, ffmpeg_return_code: int = 0, os_error: str = "") -> tuple[ExportOutputCategory, str]:
    err = os_error.lower()
    if "no space" in err:
        return ExportOutputCategory.DISK_FULL, "Brak miejsca na dysku"
    elif "permission" in err:
        return ExportOutputCategory.PERMISSION_DENIED, "Brak uprawnień do zapisu"
    elif "device" in err or "not ready" in err:
        return ExportOutputCategory.DEVICE_UNAVAILABLE, "Urządzenie niedostępne"
    elif "broken pipe" in err:
        return ExportOutputCategory.BROKEN_PIPE, "Zapis przerwany (Broken pipe)"
    elif ffmpeg_return_code != 0:
        return ExportOutputCategory.MUX_FAILURE, "Błąd muxera"
    return ExportOutputCategory.UNKNOWN, "Nieznany błąd zapisu"

__all__ = [
    "RenderError", "StorageError", "PreflightError", "SourceReadError",
    "DecoderError", "GpuError", "EncoderError", "MuxError", "AudioError",
    "TelemetryError", "ChildProcessError", "ResourceError", "RenderCancelled",
    "ErrorScope", "ExportOutputCategory", "ExportOutputError", "OutputWriteError",
    "classify_output_error", "check_preflight_storage", "check_preflight_sources",
    "estimate_required_export_space", "parse_bitrate_to_bps", "classify_mux_error",
    "validate_partial_output", "RuntimeStorageMonitor"
]
''')
