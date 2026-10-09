"""Backward compatibility shim for output_error.py -> render_errors.py."""

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

# Aliases for compatibility
ExportOutputError = StorageError
ExportOutputCategory = ErrorScope
OutputWriteError = StorageError
classify_output_error = classify_mux_error

__all__ = [
    "RenderError",
    "StorageError",
    "PreflightError",
    "SourceReadError",
    "DecoderError",
    "GpuError",
    "EncoderError",
    "MuxError",
    "AudioError",
    "TelemetryError",
    "ChildProcessError",
    "ResourceError",
    "RenderCancelled",
    "ErrorScope",
    "ExportOutputCategory",
    "ExportOutputError",
    "OutputWriteError",
    "classify_output_error",
    "check_preflight_storage",
    "check_preflight_sources",
    "estimate_required_export_space",
    "parse_bitrate_to_bps",
    "classify_mux_error",
    "validate_partial_output",
    "RuntimeStorageMonitor",
]
