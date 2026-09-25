"""Safe FIT/GPX file validation against the absolute video timeline."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from threading import Event
from typing import Iterable, Any
import xml.etree.ElementTree as ET


class ValidationState(str, Enum):
    VALID = "VALID"
    WARNING = "WARNING"
    INVALID = "INVALID"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class TelemetryFileValidationResult:
    state: ValidationState
    file_type: str
    file_path: Path
    video_start: datetime | None = None
    video_end: datetime | None = None
    telemetry_start: datetime | None = None
    telemetry_end: datetime | None = None
    overlap_seconds: float = 0.0
    nearest_gap_seconds: float | None = None
    start_delta_seconds: float | None = None
    reason_code: str = ""
    message: str = ""
    can_force_load: bool = False
    point_count: int = 0

    @property
    def accepted_without_prompt(self) -> bool:
        return self.state is ValidationState.VALID


@dataclass
class TelemetryValidationRequest:
    """Worker-to-GUI prompt payload; the worker waits without touching Qt UI."""
    result: TelemetryFileValidationResult
    accepted: bool = False
    user_override: bool = False
    completed: Event = field(default_factory=Event)


def normalize_utc(value: datetime | None) -> datetime | None:
    """Return an aware UTC datetime for both naive and aware inputs."""
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def sample_time_range(samples: Iterable[Any]) -> tuple[datetime, datetime] | None:
    """Find the min/max timestamp from timestamped sample-like values."""
    values: list[datetime] = []
    for sample in samples:
        try:
            dt = normalize_utc(sample[0])
        except (IndexError, TypeError, AttributeError):
            continue
        if dt is not None:
            values.append(dt)
    if not values:
        return None
    return min(values), max(values)


def inspect_gpx_structure(path: Path | str) -> tuple[int, int, tuple[datetime, datetime] | None, str | None]:
    """Return valid trackpoint count, timed count, range, and parse error."""
    try:
        root = ET.parse(path).getroot()
    except Exception as exc:
        return 0, 0, None, str(exc)
    point_count = 0
    timed: list[datetime] = []
    for point in root.iter():
        if not str(point.tag).split("}")[-1].lower() == "trkpt":
            continue
        try:
            lat = float(point.attrib.get("lat", "nan"))
            lon = float(point.attrib.get("lon", "nan"))
        except (TypeError, ValueError):
            continue
        if not (-90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0):
            continue
        point_count += 1
        time_el = next(
            (child for child in point.iter()
             if str(child.tag).split("}")[-1].lower() == "time"),
            None,
        )
        if time_el is None or not (time_el.text or "").strip():
            continue
        try:
            value = (time_el.text or "").strip().replace("Z", "+00:00")
            dt = datetime.fromisoformat(value)
            dt = normalize_utc(dt)
            if dt is not None:
                timed.append(dt)
        except (TypeError, ValueError):
            continue
    return point_count, len(timed), (min(timed), max(timed)) if timed else None, None


def _format_dt(value: datetime | None) -> str:
    if value is None:
        return "brak"
    return normalize_utc(value).strftime("%d.%m.%Y %H:%M:%S UTC")  # type: ignore[union-attr]


def _range_text(label: str, start: datetime | None, end: datetime | None) -> str:
    return f"{label}:\n{_format_dt(start)} – {_format_dt(end)}"


def _mismatch_message(
    file_type: str,
    video_start: datetime | None,
    video_end: datetime | None,
    telemetry_start: datetime | None,
    telemetry_end: datetime | None,
    gap: float | None,
) -> str:
    gap_text = "nieznana" if gap is None else f"około {gap / 3600.0:.1f} h"
    return (
        f"Plik {file_type} nie pasuje czasowo do materiału wideo.\n\n"
        f"{_range_text('Wideo', video_start, video_end)}\n\n"
        f"{_range_text(file_type, telemetry_start, telemetry_end)}\n\n"
        f"Najbliższa różnica: {gap_text}.\n\n"
        "Prawdopodobnie wybrano plik z innej aktywności."
    )


def validate_telemetry_range(
    *,
    file_type: str,
    file_path: Path | str,
    video_start: datetime | None,
    video_end: datetime | None,
    telemetry_start: datetime | None,
    telemetry_end: datetime | None,
    point_count: int = 0,
    parse_error: str | None = None,
) -> TelemetryFileValidationResult:
    """Classify a FIT/GPX candidate using full interval overlap semantics."""
    kind = str(file_type).upper()
    path = Path(file_path)
    v_start = normalize_utc(video_start)
    v_end = normalize_utc(video_end)
    t_start = normalize_utc(telemetry_start)
    t_end = normalize_utc(telemetry_end)

    if parse_error:
        if parse_error == "missing_file":
            return TelemetryFileValidationResult(
                ValidationState.INVALID, kind, path, v_start, v_end, t_start, t_end,
                reason_code="FILE_MISSING",
                message=f"Nie znaleziono wybranego pliku {kind}:\n{path}",
                point_count=point_count,
            )
        message = (
            f"Nie można wczytać pliku {kind}.\n\n"
            "Plik jest uszkodzony albo nie zawiera prawidłowych danych aktywności."
        )
        return TelemetryFileValidationResult(
            ValidationState.INVALID, kind, path, v_start, v_end, t_start, t_end,
            reason_code="CORRUPT_FILE", message=message, point_count=point_count,
        )
    if point_count <= 0:
        message = (
            f"Nie można wczytać pliku {kind}.\n\n"
            f"Plik nie zawiera prawidłowych danych {kind}."
        )
        return TelemetryFileValidationResult(
            ValidationState.INVALID, kind, path, v_start, v_end, t_start, t_end,
            reason_code="EMPTY_FILE", message=message,
        )
    if t_start is None or t_end is None:
        if kind == "GPX":
            message = (
                "Nie można sprawdzić zgodności czasu tego pliku GPX, "
                "ponieważ nie zawiera znaczników czasu."
            )
            return TelemetryFileValidationResult(
                ValidationState.UNKNOWN, kind, path, v_start, v_end,
                reason_code="NO_TIMESTAMPS", message=message,
                can_force_load=True, point_count=point_count,
            )
        return TelemetryFileValidationResult(
            ValidationState.INVALID, kind, path, v_start, v_end,
            reason_code="NO_TIMESTAMPS",
            message=f"Plik {kind} nie zawiera użytecznych znaczników czasu.",
            point_count=point_count,
        )
    if v_start is None or v_end is None:
        return TelemetryFileValidationResult(
            ValidationState.UNKNOWN, kind, path, v_start, v_end,
            t_start, t_end, reason_code="VIDEO_TIME_UNAVAILABLE",
            message=(
                "Nie można sprawdzić zgodności czasu materiału wideo. "
                "Możesz wczytać plik mimo to."
            ), can_force_load=True, point_count=point_count,
        )

    overlap = max(
        0.0,
        (min(v_end, t_end) - max(v_start, t_start)).total_seconds(),
    )
    start_delta = abs((t_start - v_start).total_seconds())
    if overlap > 0.0:
        return TelemetryFileValidationResult(
            ValidationState.VALID, kind, path, v_start, v_end, t_start, t_end,
            overlap_seconds=overlap, nearest_gap_seconds=0.0,
            start_delta_seconds=start_delta, reason_code="TIME_OVERLAP",
            message="Zakres czasu telemetrii pokrywa się z materiałem wideo.",
            point_count=point_count,
        )

    gap = min(
        abs((t_start - v_end).total_seconds()),
        abs((v_start - t_end).total_seconds()),
    )
    if gap <= 300.0:
        state = ValidationState.VALID
        reason = "NEARBY_TIME_GAP"
        force = False
        message = "Zakresy nie nakładają się, ale różnica mieści się w normalnym zakresie synchronizacji."
    elif gap <= 3600.0:
        state = ValidationState.WARNING
        reason = "SUSPICIOUS_TIME_GAP"
        force = True
        message = _mismatch_message(kind, v_start, v_end, t_start, t_end, gap)
    else:
        state = ValidationState.INVALID
        reason = "DATE_TIME_MISMATCH"
        force = True
        message = _mismatch_message(kind, v_start, v_end, t_start, t_end, gap)
    return TelemetryFileValidationResult(
        state, kind, path, v_start, v_end, t_start, t_end,
        overlap_seconds=0.0, nearest_gap_seconds=gap,
        start_delta_seconds=start_delta, reason_code=reason,
        message=message, can_force_load=force, point_count=point_count,
    )


def log_validation(result: TelemetryFileValidationResult, user_override: bool = False) -> None:
    """Emit one concise diagnostic block, never one line per sample."""
    print(
        "[TELEMETRY VALIDATION]\n"
        f"TYPE={result.file_type}\n"
        f"FILE={result.file_path}\n"
        f"VIDEO_START={_format_dt(result.video_start)}\n"
        f"VIDEO_END={_format_dt(result.video_end)}\n"
        f"TELEMETRY_START={_format_dt(result.telemetry_start)}\n"
        f"TELEMETRY_END={_format_dt(result.telemetry_end)}\n"
        f"OVERLAP_SECONDS={result.overlap_seconds:.3f}\n"
        f"NEAREST_GAP_SECONDS={result.nearest_gap_seconds if result.nearest_gap_seconds is not None else 'N/A'}\n"
        f"START_DELTA_SECONDS={result.start_delta_seconds if result.start_delta_seconds is not None else 'N/A'}\n"
        f"RESULT={result.state.value}\n"
        f"REASON={result.reason_code}\n"
        f"USER_OVERRIDE={bool(user_override)}",
        flush=True,
    )
