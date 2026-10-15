"""AMD export log beside the output MP4 (same base name, ``.log``).

The log is opt-out (``amd_export_logging_enabled`` in app_preferences.json,
default ON).  Every export appends a clearly separated session, so a repeated
export under the same name never destroys earlier diagnostics.  Writes go
through short-lived low-level appends (no fsync); per-frame logging is not
done here.
"""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any, Optional

SESSION_SEPARATOR = "=" * 78


def amd_export_log_path(output_file: str | Path) -> Path:
    """Log path for the final export path: ``film.mp4`` -> ``film.log``."""
    path = Path(str(output_file))
    name = path.name
    # Never derive the name from a temporary ``.part`` sidecar.
    for suffix in (".part.mp4", ".part"):
        if name.lower().endswith(suffix):
            path = path.with_name(name[: -len(suffix)])
            break
    return path.with_suffix(".log")


def resolve_amd_export_logging(options: Optional[dict], fallback: Any = True) -> bool:
    """Job snapshot value wins (queue); otherwise the current global setting."""
    value = (options or {}).get("amd_export_logging_enabled")
    if isinstance(value, bool):
        return value
    return bool(fallback) if isinstance(fallback, bool) else True


def append_amd_export_log(path: Optional[str | Path], text: str) -> None:
    """Append lines through an independent descriptor; never raises."""
    if not path:
        return
    flags = os.O_WRONLY | os.O_CREAT | os.O_APPEND
    if hasattr(os, "O_BINARY"):
        flags |= os.O_BINARY
    fd: Optional[int] = None
    try:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(str(target), flags, 0o644)
        payload = (str(text).rstrip("\r\n") + "\n").encode("utf-8", errors="replace")
        os.write(fd, payload)
    except (OSError, ValueError):
        pass
    finally:
        if fd is not None:
            try:
                os.close(fd)
            except OSError:
                pass


def begin_amd_export_log_session(
    path: Optional[str | Path],
    *,
    output: str | Path,
    job_id: str = "",
    generation_id: int = 0,
    mode: str = "DIRECT",
) -> None:
    """Start a new session block; earlier sessions in the file are kept."""
    if not path:
        return
    target = Path(path)
    try:
        previous = target.is_file() and target.stat().st_size > 0
    except OSError:
        previous = False
    lines = ["", SESSION_SEPARATOR]
    lines.append(
        f"[AMD EXPORT LOG] session_start={time.strftime('%Y-%m-%d %H:%M:%S')} "
        f"pid={os.getpid()} job_id={job_id or '-'} generation={int(generation_id or 0)} "
        f"mode={mode}"
    )
    lines.append(f"[AMD EXPORT LOG] output={output}")
    lines.append(f"[AMD EXPORT LOG] log={target}")
    if previous:
        lines.append("[AMD EXPORT LOG] previous sessions kept above (append mode)")
    lines.append(SESSION_SEPARATOR)
    append_amd_export_log(target, "\n".join(lines))


def end_amd_export_log_session(
    path: Optional[str | Path], status: str, detail: str = ""
) -> None:
    """Write the final export status (completed / cancelled / failed)."""
    if not path:
        return
    text = (
        f"[AMD EXPORT LOG] session_end={time.strftime('%Y-%m-%d %H:%M:%S')} "
        f"pid={os.getpid()} status={status}"
    )
    if detail:
        text += f"\n[AMD EXPORT LOG] detail={str(detail).strip()}"
    append_amd_export_log(path, text)
