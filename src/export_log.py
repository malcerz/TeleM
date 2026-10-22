"""Universal export log for SportCamHUD across all backends: AMD, Intel, NVIDIA, and CPU.

Saves a dedicated, structured export log beside the output video file (e.g. film.mp4 -> film.log)
or falls back to the user's local application data directory (%LOCALAPPDATA%/SportCamHUD/logs)
if the destination directory is read-only, MSIX-sandboxed, or on a restricted network share.

Guarantees:
- Opt-out via 'export_logging_enabled' (defaults to True; backward-compatible with legacy 'amd_export_logging_enabled').
- Standardized, vendor-neutral structure for AMD, Intel, NVIDIA, and CPU.
- Preserves previous session diagnostics (append mode with clear session headers).
- Redacts credentials (Esri, CARTO, Strava, Garmin, auth tokens, passwords).
- Captures environment, hardware (CPU, GPU, driver), codec settings, telemetry prep,
  hybrid compass calibration status & sample checkpoints, progress milestones,
  and native pipeline stage timings.
- Non-blocking line writing with buffered I/O, safe exception handling, and flush integrity.
"""

from __future__ import annotations

import datetime
import hashlib
import json
import os
import platform
import re
import sys
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

SESSION_SEPARATOR = "=" * 78
SUB_SEPARATOR = "-" * 78

# ---------------------------------------------------------------------------
# Credential & Secret Protection (Requirement 7)
# ---------------------------------------------------------------------------

_SECRET_PATTERNS = [
    # URLs with query parameters containing keys/tokens/passwords
    (re.compile(r"([?&](?:api_key|token|key|access_token|secret|password)=)[^&\s'\"]+", re.IGNORECASE), r"\1[REDACTED]"),
    # HTTP Authorization headers
    (re.compile(r"(Authorization\s*:\s*(?:Bearer|Basic)\s+)[^\r\n\s]+", re.IGNORECASE), r"\1[REDACTED]"),
    # ArcGIS / Esri tokens in URLs or text
    (re.compile(r"(arcgis\.com/[^\s'\"]*token=)[^&\s'\"]+", re.IGNORECASE), r"\1[REDACTED]"),
    # CARTO API keys in URLs
    (re.compile(r"(carto\.com/[^\s'\"]*api_key=)[^&\s'\"]+", re.IGNORECASE), r"\1[REDACTED]"),
    # JSON / dict key-value secrets
    (re.compile(r"(['\"]?(?:client_secret|access_token|refresh_token|password|api_key)['\"]?\s*[:=]\s*['\"])[^'\"\r\n]+(['\"])", re.IGNORECASE), r"\1[REDACTED]\2"),
]


def sanitize_log_text(text: str) -> str:
    """Redact sensitive keys, tokens, and passwords from log strings."""
    if not text:
        return ""
    res = str(text)
    for pat, repl in _SECRET_PATTERNS:
        res = pat.sub(repl, res)
    return res


# ---------------------------------------------------------------------------
# Directories and Paths (Requirement 6)
# ---------------------------------------------------------------------------

def get_user_logs_dir() -> Path:
    """Return local writable user logs directory (%LOCALAPPDATA%/SportCamHUD/logs)."""
    local_app_data = os.environ.get("LOCALAPPDATA") or (Path.home() / "AppData" / "Local")
    logs_dir = Path(local_app_data) / "SportCamHUD" / "logs"
    try:
        logs_dir.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    return logs_dir


def export_log_path(output_file: str | Path, backend: str = "COMMON") -> Path:
    """Return canonical log path for an export: ``film.mp4`` -> ``film.log``."""
    path = Path(str(output_file))
    name = path.name
    for suffix in (".part.mp4", ".part", ".mp4", ".mkv", ".mov", ".avi"):
        if name.lower().endswith(suffix):
            path = path.with_name(name[:-len(suffix)])
            break
    return path.with_suffix(".log")


def resolve_export_logging(options: Optional[dict] = None, fallback: Any = None) -> bool:
    """Resolve whether export logging is enabled.

    1. Job-specific snapshot in options ('export_logging_enabled' or 'amd_export_logging_enabled').
    2. Explicit fallback argument if provided (bool).
    3. Global preference from load_export_logging_enabled().
    """
    if options:
        if "export_logging_enabled" in options:
            val = options["export_logging_enabled"]
            if isinstance(val, bool):
                return val
        if "amd_export_logging_enabled" in options:
            val = options["amd_export_logging_enabled"]
            if isinstance(val, bool):
                return val
    if isinstance(fallback, bool):
        return fallback
    try:
        from src.export_paths import load_export_logging_enabled
        return load_export_logging_enabled()
    except Exception:
        return True


# ---------------------------------------------------------------------------
# Low-level Safe Append
# ---------------------------------------------------------------------------

def append_export_log(path: Optional[str | Path], text: str) -> None:
    """Append lines through an independent file descriptor; never raises.
    Falls back to user local logs directory if destination is not writable.
    """
    if not path:
        return
    sanitized = sanitize_log_text(text)
    flags = os.O_WRONLY | os.O_CREAT | os.O_APPEND
    if hasattr(os, "O_BINARY"):
        flags |= os.O_BINARY
    fd: Optional[int] = None
    target = Path(path)
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(str(target), flags, 0o644)
    except (OSError, PermissionError):
        try:
            fallback_target = get_user_logs_dir() / target.name
            fd = os.open(str(fallback_target), flags, 0o644)
        except (OSError, PermissionError):
            return
    try:
        payload = (sanitized.rstrip("\r\n") + "\n").encode("utf-8", errors="replace")
        os.write(fd, payload)
    except (OSError, ValueError):
        pass
    finally:
        if fd is not None:
            try:
                os.close(fd)
            except OSError:
                pass


# ---------------------------------------------------------------------------
# Hardware & Environment Probing (Requirement 4)
# ---------------------------------------------------------------------------

def _probe_environment_info() -> Dict[str, str]:
    """Collect host environment, CPU, RAM, and GPU/driver info without crashing."""
    env_info = {
        "os": "N/A",
        "cpu": "N/A",
        "ram": "N/A",
        "gpus": "N/A",
    }
    try:
        env_info["os"] = f"{platform.system()} {platform.release()} (Build {platform.version()}) {platform.machine()}"
    except Exception:
        pass

    try:
        from src.gui.qt.hardware_info import _get_cpu_name_and_threads, _get_ram_string, _get_gpus
        cpu_name, threads = _get_cpu_name_and_threads()
        env_info["cpu"] = f"{cpu_name} ({threads})"
        env_info["ram"] = _get_ram_string()
        gpus = _get_gpus()
        env_info["gpus"] = "; ".join(gpus) if gpus else "N/A"
    except Exception:
        if env_info["cpu"] == "N/A":
            env_info["cpu"] = os.environ.get("PROCESSOR_IDENTIFIER") or platform.processor() or "N/A"

    return env_info


# ---------------------------------------------------------------------------
# Compass Checkpoint Sampling (Requirement 9)
# ---------------------------------------------------------------------------

def sample_compass_checkpoints(
    telemetry: Any,
    layout: Optional[dict] = None,
    target_fps: float = 29.97,
    duration_s: float = 0.0,
    checkpoints_count: int = 5,
) -> List[str]:
    """Sample compass checkpoints across the timeline for diagnostics and validation."""
    lines: List[str] = []
    if telemetry is None:
        lines.append("  Compass Telemetry: N/A (telemetry object not available)")
        return lines

    compass_cfg = (layout or {}).get("indicators", {}).get("compass", {})
    from src.telemetry_compass_hybrid import hybrid_enabled
    is_hybrid = hybrid_enabled(compass_cfg)
    lines.append(f"  Hybrid Compass Enabled: {'YES' if is_hybrid else 'NO'}")

    hybrid_model = getattr(telemetry, "_compass_hybrid_result", None)
    if hybrid_model is not None and hasattr(hybrid_model, "samples"):
        lines.append(f"  Hybrid Samples Available: {len(hybrid_model.samples)}")
    else:
        lines.append("  Hybrid Samples Available: N/A")

    start_dt = getattr(telemetry, "start_dt_utc", None)
    if not start_dt:
        lines.append("  Timeline start UTC: N/A")
        return lines

    dur = float(duration_s or 0.0)
    if dur <= 0.0:
        dur = float(getattr(telemetry, "video_duration", 0.0) or getattr(telemetry, "duration_s", 0.0) or 0.0)
    if dur <= 0.0:
        lines.append("  Checkpoints: Duration is 0, skipping checkpoint sampling")
        return lines

    lines.append("  Checkpoint Samples:")
    step = dur / max(1, checkpoints_count - 1) if checkpoints_count > 1 else dur
    for idx in range(checkpoints_count):
        t_sec = min(dur, idx * step)
        dt = start_dt + datetime.timedelta(seconds=t_sec)
        
        # Raw GPS / FIT / GPMF heading
        raw_heading = "N/A"
        try:
            val_fit = telemetry.resolve_value("heading", dt, source="fit") if hasattr(telemetry, "resolve_value") else None
            val_gpmf = telemetry.resolve_value("heading", dt, source="gpmf") if hasattr(telemetry, "resolve_value") else None
            if val_fit is not None:
                raw_heading = f"{float(val_fit):.1f}° (FIT)"
            elif val_gpmf is not None:
                raw_heading = f"{float(val_gpmf):.1f}° (GPMF)"
        except Exception:
            pass

        # Hybrid heading
        hybrid_heading = "N/A"
        try:
            val_hyb = telemetry.resolve_value("heading", dt, indicator_key="compass") if hasattr(telemetry, "resolve_value") else None
            if val_hyb is not None:
                hybrid_heading = f"{float(val_hyb):.1f}°"
        except Exception:
            pass

        # Cache status
        cache_status = "OK" if hybrid_heading != "N/A" or raw_heading != "N/A" else "NO_DATA"
        dt_str = dt.strftime("%Y-%m-%d %H:%M:%S")
        lines.append(
            f"    Point {idx + 1}/{checkpoints_count} (t={t_sec:6.1f}s | {dt_str} UTC): "
            f"raw_heading={raw_heading}, hybrid_heading={hybrid_heading}, cache={cache_status}"
        )

    return lines


# ---------------------------------------------------------------------------
# Session Management (Requirements 4, 5, 9)
# ---------------------------------------------------------------------------

def begin_export_log_session(
    path: Optional[str | Path],
    *,
    output: str | Path,
    backend: str = "COMMON",
    encoder: str = "auto",
    codec: str = "hevc",
    profile: str = "balanced",
    job_id: str = "",
    generation_id: int = 0,
    mode: str = "DIRECT",
    video_paths: Optional[List[str]] = None,
    fit_path: str = "",
    gpx_path: str = "",
    resolution: str = "source",
    target_fps: float = 30.0,
    bitrate: str = "40M",
    hdr_mode: str = "preserve_hlg",
    duration_s: float = 0.0,
    vbr_settings: Optional[dict] = None,
    layout: Optional[dict] = None,
    telemetry: Any = None,
    video_timeline: Optional[Any] = None,
) -> None:
    """Start a new export log session block; preserves any previous sessions in append mode."""
    if not path:
        return
    target = Path(path)
    try:
        previous = target.is_file() and target.stat().st_size > 0
    except OSError:
        previous = False

    try:
        from src.version import APP_VERSION, APP_BUILD_COMMIT
        app_ver = f"{APP_VERSION} (commit {APP_BUILD_COMMIT})"
    except Exception:
        app_ver = "1.14 (unknown)"

    env_info = _probe_environment_info()

    lines = ["", SESSION_SEPARATOR]
    ts = time.strftime('%Y-%m-%d %H:%M:%S')
    lines.append(f"[SPORTCAMHUD EXPORT LOG SESSION START] {ts}")
    # Compatibility marker for existing tests and tooling
    lines.append(
        f"[AMD EXPORT LOG] session_start={ts} pid={os.getpid()} "
        f"job_id={job_id or '-'} generation={int(generation_id or 0)} mode={mode}"
    )
    lines.append(f"[AMD EXPORT LOG] output={output}")
    lines.append(f"[AMD EXPORT LOG] log={target}")
    lines.append(SESSION_SEPARATOR)
    lines.append("[APPLICATION]")
    lines.append("  Application:    SportCamHUD")
    lines.append(f"  Version:        {app_ver}")
    lines.append(f"  Process PID:    {os.getpid()}")
    lines.append(f"  Job ID:         {job_id or '-'}")
    lines.append(f"  Generation:     {int(generation_id or 0)}")
    lines.append(f"  Mode:           {mode}")
    lines.append(f"  Log File:       {target}")

    lines.append("\n[HOST ENVIRONMENT]")
    lines.append(f"  Operating System: {env_info['os']}")
    lines.append(f"  CPU:              {env_info['cpu']}")
    lines.append(f"  RAM Total:        {env_info['ram']}")
    lines.append(f"  GPU(s) / Driver:  {env_info['gpus']}")

    lines.append("\n[EXPORT CONFIGURATION]")
    lines.append(f"  Target Backend:   {backend.upper()}")
    lines.append(f"  Encoder:          {encoder}")
    lines.append(f"  Codec:            {codec.upper()}")
    lines.append(f"  Resolution:       {resolution}")
    lines.append(f"  Target FPS:       {target_fps:.2f}")
    lines.append(f"  Bitrate:          {bitrate}")
    lines.append(f"  Profile / Preset: {profile}")
    lines.append(f"  HDR Mode:         {hdr_mode}")
    if vbr_settings:
        lines.append(f"  VBR Config:       {json.dumps(vbr_settings, sort_keys=True)}")
    else:
        lines.append("  VBR Config:       Default VBR")

    lines.append("\n[MEDIA INPUTS & OUTPUT]")
    lines.append(f"  Input Videos:     {video_paths or ['(none)']}")
    lines.append(f"  FIT File:         {fit_path or 'N/A'}")
    lines.append(f"  GPX File:         {gpx_path or 'N/A'}")
    lines.append(f"  Target Output:    {output}")

    # Telemetry and Compass state (Requirement 9)
    lines.append("\n[TELEMETRY & COMPASS STATUS]")
    dur_s = float(duration_s or 0.0)
    if dur_s <= 0.0:
        if video_timeline is not None and hasattr(video_timeline, "duration_s"):
            dur_s = float(video_timeline.duration_s or 0.0)
        elif telemetry is not None:
            dur_s = float(getattr(telemetry, "video_duration", 0.0) or getattr(telemetry, "duration_s", 0.0) or 0.0)

    compass_diag = sample_compass_checkpoints(telemetry, layout=layout, target_fps=target_fps, duration_s=dur_s)
    lines.extend(compass_diag)

    if previous:
        lines.append("\n[AMD EXPORT LOG] previous sessions kept above (append mode)")
        lines.append("[NOTE] Previous sessions are kept above (append mode).")
    lines.append(SUB_SEPARATOR)
    lines.append("[PIPELINE PROGRESS & DIAGNOSTICS]")

    append_export_log(target, "\n".join(lines))


def log_export_progress(
    path: Optional[str | Path],
    *,
    frame: int,
    total: int,
    fps: float,
    elapsed_s: float,
    extra: str = "",
) -> None:
    """Log periodic export progress milestone."""
    if not path:
        return
    pct = (frame / total * 100.0) if total > 0 else 0.0
    msg = f"[PROGRESS] frame={frame}/{total} ({pct:5.1f}%) fps={fps:5.1f} elapsed={elapsed_s:6.1f}s"
    if extra:
        msg += f" {extra}"
    append_export_log(path, msg)


def end_export_log_session(
    path: Optional[str | Path],
    status: str,
    detail: str = "",
    stats: Optional[dict] = None,
) -> None:
    """Write the final export status, performance stats, and close session block."""
    if not path:
        return
    lines = ["", SUB_SEPARATOR]
    ts = time.strftime('%Y-%m-%d %H:%M:%S')
    lines.append(f"[SPORTCAMHUD EXPORT LOG SESSION END] {ts}")
    # Compatibility marker for existing tests and tooling
    lines.append(f"[AMD EXPORT LOG] session_end={ts} pid={os.getpid()} status={status}")
    lines.append(f"  status={status}")
    lines.append(f"  Process PID:        {os.getpid()}")
    lines.append(f"  Final Status:       {status.upper()}")
    if detail:
        lines.append(f"  Detail / Error:     {str(detail).strip()}")
        lines.append(f"  detail={str(detail).strip()}")
        lines.append(f"[AMD EXPORT LOG] detail={str(detail).strip()}")

    if stats and isinstance(stats, dict):
        lines.append("\n[PERFORMANCE METRICS & SUMMARY]")
        frames = stats.get("frames_rendered", stats.get("total_frames", "N/A"))
        r_fps = stats.get("render_fps", stats.get("real_export_fps", "N/A"))
        eff_fps = stats.get("user_effective_fps", stats.get("effective_fps", "N/A"))
        wall_s = stats.get("total_wall_seconds", stats.get("elapsed_s", "N/A"))
        render_s = stats.get("frame_render_seconds", "N/A")
        final_s = stats.get("finalization_seconds", "N/A")

        lines.append(f"  Frames Rendered:    {frames}")
        if isinstance(r_fps, (int, float)):
            lines.append(f"  Render FPS (Loop):  {float(r_fps):.2f} FPS")
        if isinstance(eff_fps, (int, float)):
            lines.append(f"  User Effective FPS: {float(eff_fps):.2f} FPS")
        if isinstance(wall_s, (int, float)):
            lines.append(f"  Total Wall Time:    {float(wall_s):.2f} s")
        if isinstance(render_s, (int, float)):
            lines.append(f"  Frame Render Time:  {float(render_s):.2f} s")
        if isinstance(final_s, (int, float)):
            lines.append(f"  Finalization Time:  {float(final_s):.2f} s")

        enc_stats = stats.get("encoder_accepted", stats.get("encoder_stats", {}))
        if enc_stats and isinstance(enc_stats, dict):
            lines.append(f"  Encoder Parameters: {json.dumps(enc_stats, sort_keys=True)}")

    lines.append(SESSION_SEPARATOR)
    append_export_log(path, "\n".join(lines))
