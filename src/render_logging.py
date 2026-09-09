"""Shared verbosity policy for render progress and diagnostics."""
from __future__ import annotations

import builtins
import os
from enum import IntEnum
from typing import Any


class RenderLogLevel(IntEnum):
    """Ordered renderer logging levels used by Python-side diagnostics."""

    ERROR = 0
    INFO = 1
    DEBUG = 2
    TRACE = 3


def render_log_level() -> RenderLogLevel:
    """Resolve the process logging level without changing production defaults."""
    if os.environ.get("TELEM_RENDER_DEBUG", "").strip().lower() in {
        "1", "true", "yes", "on",
    }:
        return RenderLogLevel.DEBUG
    raw = os.environ.get("TELEM_RENDER_LOG_LEVEL", "INFO").strip().upper()
    try:
        return RenderLogLevel[raw]
    except KeyError:
        return RenderLogLevel.INFO


def render_log(level: RenderLogLevel, *args: Any, **kwargs: Any) -> None:
    """Emit a levelled diagnostic; TRACE is never sent to the hot path by default."""
    if RenderLogLevel(level) <= render_log_level():
        builtins.print(*args, **kwargs)


def render_debug_enabled() -> bool:
    """Return whether verbose renderer diagnostics were explicitly requested."""
    return render_log_level() >= RenderLogLevel.DEBUG


def render_debug_print(*args: Any, **kwargs: Any) -> None:
    """Print a detailed render diagnostic only in debug mode."""
    render_log(RenderLogLevel.DEBUG, *args, **kwargs)


def render_trace_print(*args: Any, **kwargs: Any) -> None:
    """Print trace diagnostics only when explicitly requested."""
    render_log(RenderLogLevel.TRACE, *args, **kwargs)


_ALWAYS_VISIBLE = (
    "ERROR", "WARNING", "Error", "error:", "failed", "FAIL", "cancel", "Cancel",
    "Missing", "exception", "Exception", "Falling back",
    "Fallback reason", "not available", "unavailable", "CACHE MISS DURING RENDER",
    "No 'record'", "No timed", "No matching FIT", "not found", "No input",
    "missing or empty", "missing at",
)


def render_print(*args: Any, **kwargs: Any) -> None:
    """Default exporter print policy: keep actionable diagnostics and summaries."""
    if render_debug_enabled():
        builtins.print(*args, **kwargs)
        return
    message = " ".join(str(arg) for arg in args)
    normalized = message.lstrip()
    if any(token in message for token in _ALWAYS_VISIBLE):
        builtins.print(*args, **kwargs)
        return
    if normalized.startswith("=== RENDER COMPLETE ==="):
        builtins.print(*args, **kwargs)
        return
    noisy_prefixes = (
        "[AMD NATIVE", "[HUD]", "[Progress]", "[TELEMETRY CHANNELS",
        "GPMF records", "FIT records", "GPX records", "CHART_TRACE",
        "[TIMING", "[CHECKPOINT]", "[D3D11", "[AMF", "[MF",
        "AMD ETAP", "AMD Native", "AMD_OVERLAY_PROFILE", "AMD_SYNC_FRAME_ACCOUNTING",
        "AMD_MAP_PARITY", "AMD_LEAN_PARITY", "[AMD Map Tile Stats]",
        "[AMD Map", "[AMD GAUGE", "AMD_NATIVE", "AMD_",
        "=== AMD REAL PRODUCTION EFFECTIVE CONFIG ===",
        "[FIT]", "[GPX]", "[SmartSync]", "[TelemetryManager]", "[MultiFile",
        "[HUD Resolution]", "[STREAM", "[INTEL]", "[NVIDIA]", "[GPU]",
        "[CUT]", "[NV1]", "FFmpeg streaming cmd:", "FFmpeg final command:",
        "=== NVIDIA", "PREPARE                ", "WORKER_INIT", "FFMPEG_STARTUP",
        "FIRST_FRAME_LATENCY", "FRAME_PIPELINE", "FFMPEG_DRAIN_FINALIZE",
        "POSTPROCESS", "PRODUCTION_TOTAL", "clips=", "clip ",
        "CPU_GPU_PIPELINE", "QUEUE_DEPTH", "VP_STATE", "VP_POOL", "AMF_QUERY",
        "MAP_PATH", "MAP_ALIGN", "GAUGE_GPU", "CHART_GPU", "LEAN_GPU",
        "HUD_MODE", "HUD_UPLOAD", "NV12_COMPOSITOR", "PROFILING",
        "============================================",
    )
    if normalized.startswith(noisy_prefixes):
        return
    builtins.print(*args, **kwargs)
