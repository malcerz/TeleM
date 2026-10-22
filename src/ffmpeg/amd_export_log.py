"""AMD export log compatibility module.

Delegates all operations to the universal export log implementation (src.export_log)
while preserving full backward compatibility for existing callers and tests.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from src.export_log import (
    SESSION_SEPARATOR,
    append_export_log,
    begin_export_log_session,
    end_export_log_session,
    export_log_path,
    resolve_export_logging,
)


def amd_export_log_path(output_file: str | Path) -> Path:
    """Log path for the final export path: ``film.mp4`` -> ``film.log``."""
    return export_log_path(output_file, backend="AMD")


def resolve_amd_export_logging(options: Optional[dict], fallback: Any = True) -> bool:
    """Job snapshot value wins (queue); otherwise the current global setting."""
    return resolve_export_logging(options, fallback)


def append_amd_export_log(path: Optional[str | Path], text: str) -> None:
    """Append lines through an independent descriptor; never raises."""
    append_export_log(path, text)


def begin_amd_export_log_session(
    path: Optional[str | Path],
    *,
    output: str | Path,
    job_id: str = "",
    generation_id: int = 0,
    mode: str = "DIRECT",
) -> None:
    """Start a new session block; earlier sessions in the file are kept."""
    begin_export_log_session(
        path,
        output=output,
        backend="AMD",
        job_id=job_id,
        generation_id=generation_id,
        mode=mode,
    )


def end_amd_export_log_session(
    path: Optional[str | Path], status: str, detail: str = ""
) -> None:
    """Write the final export status (completed / cancelled / failed)."""
    end_export_log_session(path, status, detail)
