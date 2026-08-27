"""Versioned, data-only cache for processed GPMF telemetry.

The cache deliberately stores canonical samples rather than GUI/controller
objects. JSON+gzip keeps reads safe (no executable deserialization) and the
source fingerprint prevents stale results from being reused.
"""

from __future__ import annotations

import gzip
import json
from datetime import datetime
from pathlib import Path
from typing import Any


PROCESSED_CACHE_VERSION = 1
PROCESSED_CACHE_SUFFIX = ".telemetry.json.gz"

_FIELDS = (
    "speed_samples", "alt_samples", "track_samples", "iso_samples",
    "exposure_samples", "temperature_samples", "slope_samples",
    "accelerometer_samples", "gyroscope_samples", "gps_track",
    "heading_samples", "start_dt_utc",
)


def processed_cache_path(source_path: Path) -> Path:
    return source_path.with_name(source_path.stem + PROCESSED_CACHE_SUFFIX)


def _encode(value: Any) -> Any:
    if isinstance(value, datetime):
        return {"__datetime__": value.isoformat()}
    if isinstance(value, tuple):
        return [_encode(item) for item in value]
    if isinstance(value, list):
        return [_encode(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _encode(item) for key, item in value.items()}
    return value


def _decode(value: Any) -> Any:
    if isinstance(value, dict):
        if set(value) == {"__datetime__"}:
            return datetime.fromisoformat(value["__datetime__"])
        return {key: _decode(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_decode(item) for item in value]
    return value


def _contract(source_path: Path) -> dict[str, Any]:
    stat = source_path.stat()
    return {
        "version": PROCESSED_CACHE_VERSION,
        "source_size": stat.st_size,
        "source_mtime_ns": stat.st_mtime_ns,
    }


def write_processed_cache(source_path: Path, telemetry: Any) -> Path:
    path = processed_cache_path(source_path)
    payload = {
        "_telem_processed_cache": _contract(source_path),
        "fields": {
            field: _encode(getattr(telemetry, field, None))
            for field in _FIELDS
        },
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt", encoding="utf-8", compresslevel=1) as handle:
        json.dump(payload, handle, separators=(",", ":"), ensure_ascii=False)
    return path


def read_processed_cache(source_path: Path) -> dict[str, Any] | None:
    path = processed_cache_path(source_path)
    if not path.exists():
        return None
    try:
        with gzip.open(path, "rt", encoding="utf-8") as handle:
            payload = json.load(handle)
        contract = payload.get("_telem_processed_cache")
        if contract != _contract(source_path):
            return None
        fields = payload.get("fields")
        if not isinstance(fields, dict):
            return None
        return {field: _decode(fields.get(field)) for field in _FIELDS}
    except (OSError, ValueError, TypeError, KeyError):
        return None


def apply_processed_cache(telemetry: Any, fields: dict[str, Any]) -> None:
    def _sample_tuples(value):
        if not isinstance(value, list):
            return value
        restored = []
        for item in value:
            if isinstance(item, list):
                item = list(item)
                if len(item) >= 2 and isinstance(item[1], list):
                    item[1] = tuple(item[1])
                restored.append(tuple(item))
            else:
                restored.append(item)
        return restored

    for field in _FIELDS:
        if field == "start_dt_utc":
            setattr(telemetry, field, fields.get(field))
        else:
            setattr(telemetry, field, _sample_tuples(fields.get(field) or []))
    if getattr(telemetry, "accelerometer_samples", None):
        telemetry._set_vector_series(telemetry.accelerometer_samples, "accel")
    if getattr(telemetry, "gyroscope_samples", None):
        telemetry._set_vector_series(telemetry.gyroscope_samples, "gyro")
