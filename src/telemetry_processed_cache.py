"""Versioned, data-only binary cache for processed GPMF telemetry.

The cache stores canonical samples directly as contiguous NumPy arrays (.npz)
rather than serialized Python/JSON trees. This eliminates multi-second
Python object encoding/decoding overhead while preserving exact data parity
and atomic, fail-safe disk persistence.
"""

from __future__ import annotations

import json
import math
import os
import threading
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np


# Version 5 records the GPMF GPS anchor timeline projection correction:
# prevents shifting GPMF timed/vector streams forward by the initial GPS lock delay.
PROCESSED_CACHE_VERSION = 5
PROCESSED_CACHE_SUFFIX = ".telemetry.npz"

_SCALAR_FIELDS = (
    "speed_samples", "alt_samples", "track_samples", "iso_samples",
    "exposure_samples", "temperature_samples", "slope_samples", "heading_samples",
)
_VECTOR_FIELDS = ("accelerometer_samples", "gyroscope_samples")
_FIELDS = (
    "speed_samples", "alt_samples", "track_samples", "iso_samples",
    "exposure_samples", "temperature_samples", "slope_samples",
    "accelerometer_samples", "gyroscope_samples", "gps_track",
    "heading_samples", "start_dt_utc",
)


_LAZY_AUDIT_LOCK = threading.Lock()
_LAZY_AUDIT_SEEN: set[tuple[int, int]] = set()


class LazySampleList(list):
    """Array-backed lazy list of telemetry sample tuples.

    Avoids creating hundreds of thousands of Python datetime and tuple objects
    during cache load, while remaining 100% drop-in compatible with standard Python
    lists (indexing, slicing, iteration, equality, bisect, len, bool).
    """
    __slots__ = (
        "_arr", "_is_vector", "_tz_aware", "_materialized", "_audit_label"
    )

    def __init__(
        self,
        arr: np.ndarray,
        is_vector: bool = False,
        tz_aware: bool = True,
        audit_label: str = "",
    ):
        super().__init__()
        self._arr = arr
        self._is_vector = is_vector
        self._tz_aware = tz_aware
        self._materialized = False
        self._audit_label = str(audit_label or "")

    def _audit_materialization(self) -> None:
        """Emit one opt-in provenance record before an expensive expansion."""
        if str(os.environ.get("TELEM_LAZY_MATERIALIZATION_AUDIT", "")).strip().upper() not in {
            "1", "YES", "ON", "TRUE"
        }:
            return
        key = (os.getpid(), id(self))
        with _LAZY_AUDIT_LOCK:
            if key in _LAZY_AUDIT_SEEN:
                return
            _LAZY_AUDIT_SEEN.add(key)
        count = len(self._arr) if self._arr is not None else 0
        stack = "".join(traceback.format_stack(limit=18)[:-1]).rstrip()
        print(
            "[LAZY MATERIALIZE AUDIT] "
            f"label={self._audit_label or '<unlabelled>'} "
            f"count={count} vector={int(self._is_vector)}\n{stack}",
            flush=True,
        )

    def _materialize(self) -> None:
        if not self._materialized:
            self._audit_materialization()
            self._materialized = True
            if self._arr is None or len(self._arr) == 0:
                return
            utc = timezone.utc
            from_ts = datetime.fromtimestamp
            ts = self._arr[:, 0]
            if self._tz_aware:
                dts = [from_ts(t, tz=utc) for t in ts]
            else:
                dts = [from_ts(t, tz=utc).replace(tzinfo=None) for t in ts]

            if self._is_vector:
                # arr is [ts, x, y, z]
                xyz = list(zip(self._arr[:, 1], self._arr[:, 2], self._arr[:, 3]))
                super().extend(zip(dts, xyz))
            elif self._arr.ndim == 2 and self._arr.shape[1] == 3:
                # gps track [ts, lat, lon]
                super().extend(zip(dts, self._arr[:, 1], self._arr[:, 2]))
            elif self._arr.ndim == 2 and self._arr.shape[1] >= 2:
                # scalar [ts, val]
                isnan = math.isnan
                vals = [None if isnan(v) else v for v in self._arr[:, 1]]
                super().extend(zip(dts, vals))

    def __len__(self) -> int:
        if not self._materialized:
            return len(self._arr) if self._arr is not None else 0
        return super().__len__()

    def __bool__(self) -> bool:
        return len(self) != 0

    def __getitem__(self, item: Any) -> Any:
        self._materialize()
        return super().__getitem__(item)

    def __iter__(self) -> Any:
        self._materialize()
        return super().__iter__()

    def __reduce_ex__(self, protocol: int) -> Any:
        """Serialize without invoking the list-subclass reconstruction path.

        CPython's default reduction for ``list`` subclasses restores list items
        before slot state.  That ordering calls our ``extend`` while the lazy
        fields do not exist yet.  Keep an unmaterialized instance array-backed;
        once materialized, the list contents are authoritative and the stale
        backing array is deliberately omitted.
        """
        del protocol  # The reconstruction contract is protocol-independent.
        if self._materialized:
            items = tuple(list.__iter__(self))
            arr = None
        else:
            items = None
            arr = self._arr
        return (
            _rebuild_lazy_sample_list,
            (arr, self._is_vector, self._tz_aware, items),
        )

    def __reduce__(self) -> Any:
        return self.__reduce_ex__(4)

    def extend(self, iterable: Any) -> None:
        if (
            not self._materialized
            and isinstance(iterable, LazySampleList)
            and not iterable._materialized
            and self._arr is not None
            and iterable._arr is not None
        ):
            self._arr = np.concatenate([self._arr, iterable._arr], axis=0)
            return
        self._materialize()
        super().extend(iterable)

    def append(self, item: Any) -> None:
        self._materialize()
        super().append(item)

    def insert(self, index: int, item: Any) -> None:
        self._materialize()
        super().insert(index, item)

    def __setitem__(self, item: Any, value: Any) -> None:
        self._materialize()
        super().__setitem__(item, value)

    def __delitem__(self, item: Any) -> None:
        self._materialize()
        super().__delitem__(item)

    def clear(self) -> None:
        self._materialize()
        super().clear()

    def pop(self, index: int = -1) -> Any:
        self._materialize()
        return super().pop(index)

    def remove(self, value: Any) -> None:
        self._materialize()
        super().remove(value)

    def __iadd__(self, iterable: Any) -> "LazySampleList":
        self.extend(iterable)
        return self

    def __imul__(self, count: int) -> "LazySampleList":
        self._materialize()
        list.__imul__(self, count)
        return self

    def reverse(self) -> None:
        self._materialize()
        super().reverse()

    def sort(self, *args: Any, **kwargs: Any) -> None:
        if not self._materialized and self._arr is not None:
            key = kwargs.get("key")
            reverse = kwargs.get("reverse", False)
            if not args and key is None:
                order = np.argsort(self._arr[:, 0])
                if reverse:
                    order = order[::-1]
                self._arr = self._arr[order]
                return
        self._materialize()
        super().sort(*args, **kwargs)

    def sort_by_timestamp(self) -> None:
        """Sort the backing series by timestamp without expanding Python tuples."""
        if not self._materialized and self._arr is not None:
            if len(self._arr) > 1:
                self._arr = self._arr[np.argsort(self._arr[:, 0], kind="stable")]
            return
        list.sort(self, key=lambda sample: sample[0])

    def __eq__(self, other: Any) -> bool:
        self._materialize()
        return super().__eq__(other)

    def __repr__(self) -> str:
        self._materialize()
        return super().__repr__()


def _rebuild_lazy_sample_list(
    arr: np.ndarray | None,
    is_vector: bool,
    tz_aware: bool,
    items: tuple[Any, ...] | None,
) -> LazySampleList:
    """Rebuild a fully initialized lazy list before restoring list contents."""
    result = LazySampleList(arr, is_vector=is_vector, tz_aware=tz_aware)
    if items is not None:
        list.extend(result, items)
        result._materialized = True
    return result


def processed_cache_path(source_path: Path) -> Path:
    return source_path.with_name(source_path.stem + PROCESSED_CACHE_SUFFIX)


def _dt_to_ts(dt: datetime) -> float:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc).timestamp()
    return dt.timestamp()


def _contract(source_path: Path) -> dict[str, Any]:
    stat = source_path.stat()
    return {
        "version": PROCESSED_CACHE_VERSION,
        "source_size": stat.st_size,
        "source_mtime_ns": stat.st_mtime_ns,
    }


def _encode(value: Any) -> Any:
    """Legacy helper preserved for backward compatibility with external scripts."""
    if isinstance(value, datetime):
        return {"__datetime__": value.isoformat()}
    if isinstance(value, (tuple, list)):
        return [_encode(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _encode(item) for key, item in value.items()}
    return value


def _decode(value: Any) -> Any:
    """Legacy helper preserved for backward compatibility with external scripts."""
    if isinstance(value, dict):
        if set(value) == {"__datetime__"}:
            return datetime.fromisoformat(value["__datetime__"])
        return {key: _decode(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_decode(item) for item in value]
    return value


def write_processed_cache(source_path: Path, telemetry: Any) -> Path:
    """Write processed telemetry cache atomically as NumPy binary archive (.npz)."""
    stat = source_path.stat()
    path = processed_cache_path(source_path)

    tz_aware = {}
    arrays = {}

    start_dt = getattr(telemetry, "start_dt_utc", None)
    start_dt_str = start_dt.isoformat() if isinstance(start_dt, datetime) else None

    # 1. Scalar streams (shape: [N, 2] -> [timestamp, value])
    for f in _SCALAR_FIELDS:
        arr = getattr(telemetry, f"{f[:f.rfind('_')]}_array" if "_" in f else f"{f}_array", None)
        if isinstance(arr, np.ndarray) and arr.ndim == 2 and arr.shape[1] == 2:
            arrays[f] = arr
            tz_aware[f] = getattr(telemetry, "_tz_aware", {}).get(f, True)
            continue

        samples = getattr(telemetry, f, None) or []
        if not samples:
            arrays[f] = np.zeros((0, 2), dtype=np.float64)
            continue
        tz_aware[f] = (samples[0][0].tzinfo is not None)
        n = len(samples)
        arr = np.empty((n, 2), dtype=np.float64)
        arr[:, 0] = [_dt_to_ts(s[0]) for s in samples]
        arr[:, 1] = [np.nan if s[1] is None else float(s[1]) for s in samples]
        arrays[f] = arr

    # 2. GPS Track (shape: [N, 3] -> [timestamp, lat, lon])
    arr_gps = getattr(telemetry, "gps_array", None)
    if isinstance(arr_gps, np.ndarray) and arr_gps.ndim == 2 and arr_gps.shape[1] == 3:
        arrays["gps_track"] = arr_gps
        tz_aware["gps_track"] = getattr(telemetry, "_tz_aware", {}).get("gps_track", True)
    else:
        gps = getattr(telemetry, "gps_track", None) or []
        if gps:
            tz_aware["gps_track"] = (gps[0][0].tzinfo is not None)
            n = len(gps)
            arr = np.empty((n, 3), dtype=np.float64)
            arr[:, 0] = [_dt_to_ts(s[0]) for s in gps]
            arr[:, 1] = [float(s[1]) for s in gps]
            arr[:, 2] = [float(s[2]) for s in gps]
            arrays["gps_track"] = arr
        else:
            arrays["gps_track"] = np.zeros((0, 3), dtype=np.float64)

    # 3. Vector streams: accel, gyro (shape: [N, 4] -> [timestamp, x, y, z])
    for vf in _VECTOR_FIELDS:
        arr_vec = getattr(telemetry, f"{vf[:vf.rfind('_')]}_array" if "_" in vf else f"{vf}_array", None)
        if isinstance(arr_vec, np.ndarray) and arr_vec.ndim == 2 and arr_vec.shape[1] == 4:
            arrays[vf] = arr_vec
            tz_aware[vf] = getattr(telemetry, "_tz_aware", {}).get(vf, True)
            continue

        samples = getattr(telemetry, vf, None) or []
        if samples:
            if hasattr(samples, "_arr") and samples._arr is not None:
                arrays[vf] = samples._arr
                tz_aware[vf] = getattr(samples, "_tz_aware", True)
                continue
            tz_aware[vf] = (samples[0][0].tzinfo is not None)
            n = len(samples)
            arr = np.empty((n, 4), dtype=np.float64)
            arr[:, 0] = [_dt_to_ts(s[0]) for s in samples]
            arr[:, 1:] = [s[1] for s in samples]
            arrays[vf] = arr
        else:
            arrays[vf] = np.zeros((0, 4), dtype=np.float64)

    meta = {
        "version": PROCESSED_CACHE_VERSION,
        "source_size": stat.st_size,
        "source_mtime_ns": stat.st_mtime_ns,
        "start_dt_utc": start_dt_str,
        "tz_aware": tz_aware,
    }
    meta_json = json.dumps(meta, separators=(",", ":")).encode("utf-8")
    arrays["__meta__"] = np.frombuffer(meta_json, dtype=np.uint8)

    # Atomic write to temporary file with flush & fsync before replacement
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_name(f"{path.stem}_{os.getpid()}_{time.time_ns()}.tmp.npz")
    try:
        with open(temp_path, "wb") as f:
            np.savez(f, **arrays)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp_path, path)
    finally:
        if temp_path.exists():
            try:
                temp_path.unlink()
            except OSError:
                pass

    arr_t = arrays.get("temperature_samples")
    if arr_t is not None and len(arr_t) > 0:
        print(f"[TMPC Cache] write_count={len(arr_t)}", flush=True)

    return path


def read_processed_cache_arrays(
    source_path: Path
) -> tuple[dict[str, np.ndarray], dict[str, Any]] | tuple[None, None]:
    """Fast-path reader returning raw NumPy arrays and metadata dictionary directly.

    Eliminates intermediate Python object tree creation for maximum warm-load speed.
    """
    path = processed_cache_path(source_path)
    if not path.exists():
        return None, None

    try:
        stat = source_path.stat()
        with np.load(path) as npz:
            if "__meta__" not in npz:
                return None, None
            meta_json = npz["__meta__"].tobytes().decode("utf-8")
            meta = json.loads(meta_json)
            if (
                meta.get("version") != PROCESSED_CACHE_VERSION
                or meta.get("source_size") != stat.st_size
                or meta.get("source_mtime_ns") != stat.st_mtime_ns
            ):
                return None, None
            arrays = {k: npz[k] for k in npz.files if k != "__meta__"}
            arr_t = arrays.get("temperature_samples")
            if arr_t is not None and len(arr_t) > 0:
                print(f"[TMPC Cache] read_count={len(arr_t)}", flush=True)
            return arrays, meta
    except Exception:
        return None, None


def read_processed_cache(source_path: Path) -> dict[str, Any] | None:
    """Read processed telemetry cache from binary archive (.npz).

    Returns a dict with canonical telemetry streams on cache hit, or None on miss/invalidation.
    High-frequency streams (ACCL, GYRO) use LazySampleList to avoid upfront object creation.
    """
    arrays, meta = read_processed_cache_arrays(source_path)
    if arrays is None or meta is None:
        return None

    try:
        tz_aware = meta.get("tz_aware", {})
        utc = timezone.utc
        from_ts = datetime.fromtimestamp
        isnan = math.isnan

        result: dict[str, Any] = {}

        # 1. start_dt_utc
        s_dt = meta.get("start_dt_utc")
        if s_dt:
            parsed_s_dt = datetime.fromisoformat(s_dt)
            # Sanity check: if cached start_dt_utc is before 2022 (e.g. uncalibrated camera clock before GPS lock),
            # resolve the true clip timestamp
            if parsed_s_dt.year < 2022:
                try:
                    from src.multifile import resolve_clip_timestamp
                    res = resolve_clip_timestamp(source_path)
                    if res.absolute_start_dt is not None:
                        parsed_s_dt = res.absolute_start_dt.replace(tzinfo=utc) if res.absolute_start_dt.tzinfo is None else res.absolute_start_dt
                except Exception:
                    pass
            result["start_dt_utc"] = parsed_s_dt
        else:
            result["start_dt_utc"] = None

        # 2. Scalar streams
        for f in _SCALAR_FIELDS:
            arr = arrays.get(f)
            if arr is None or len(arr) == 0:
                result[f] = []
                continue
            aware = tz_aware.get(f, True)
            ts_col = arr[:, 0]
            val_col = arr[:, 1]
            if aware:
                result[f] = [
                    (from_ts(t, tz=utc), None if isnan(v) else v)
                    for t, v in zip(ts_col, val_col)
                ]
            else:
                result[f] = [
                    (from_ts(t, tz=utc).replace(tzinfo=None), None if isnan(v) else v)
                    for t, v in zip(ts_col, val_col)
                ]

        # 3. GPS Track
        arr_gps = arrays.get("gps_track")
        if arr_gps is None or len(arr_gps) == 0:
            result["gps_track"] = []
        else:
            aware = tz_aware.get("gps_track", True)
            if aware:
                result["gps_track"] = [
                    (from_ts(t, tz=utc), lat, lon)
                    for t, lat, lon in zip(arr_gps[:, 0], arr_gps[:, 1], arr_gps[:, 2])
                ]
            else:
                result["gps_track"] = [
                    (from_ts(t, tz=utc).replace(tzinfo=None), lat, lon)
                    for t, lat, lon in zip(arr_gps[:, 0], arr_gps[:, 1], arr_gps[:, 2])
                ]

        # 4. Vector streams (accel, gyro): array-backed LazySampleList
        for vf in _VECTOR_FIELDS:
            arr = arrays.get(vf)
            if arr is None or len(arr) == 0:
                result[vf] = []
            else:
                aware = tz_aware.get(vf, True)
                result[vf] = LazySampleList(arr, is_vector=True, tz_aware=aware)

        # Attach raw arrays and metadata for direct zero-copy apply
        result["_arrays"] = arrays
        result["_meta"] = meta
        result["_cache_suffix"] = PROCESSED_CACHE_SUFFIX
        result["_cache_path"] = str(processed_cache_path(source_path))
        return result
    except Exception:
        return None


def apply_processed_cache_arrays(
    telemetry: Any, arrays: dict[str, np.ndarray], meta: dict[str, Any]
) -> None:
    """Directly populate TelemetryDataManager from raw NumPy arrays and metadata."""
    tz_aware = meta.get("tz_aware", {})
    s_dt = meta.get("start_dt_utc")
    telemetry.start_dt_utc = datetime.fromisoformat(s_dt) if s_dt else None

    # Scalar streams & GPS
    utc = timezone.utc
    from_ts = datetime.fromtimestamp
    isnan = math.isnan

    for f in _SCALAR_FIELDS:
        arr = arrays.get(f)
        setattr(telemetry, f"{f[:f.rfind('_')]}_array" if "_" in f else f"{f}_array", arr)
        if arr is None or len(arr) == 0:
            setattr(telemetry, f, [])
            continue
        aware = tz_aware.get(f, True)
        ts_col = arr[:, 0]
        val_col = arr[:, 1]
        if aware:
            setattr(telemetry, f, [
                (from_ts(t, tz=utc), None if isnan(v) else v)
                for t, v in zip(ts_col, val_col)
            ])
        else:
            setattr(telemetry, f, [
                (from_ts(t, tz=utc).replace(tzinfo=None), None if isnan(v) else v)
                for t, v in zip(ts_col, val_col)
            ])

    arr_gps = arrays.get("gps_track")
    telemetry.gps_array = arr_gps
    if arr_gps is None or len(arr_gps) == 0:
        telemetry.gps_track = []
    else:
        aware = tz_aware.get("gps_track", True)
        if aware:
            telemetry.gps_track = [
                (from_ts(t, tz=utc), lat, lon)
                for t, lat, lon in zip(arr_gps[:, 0], arr_gps[:, 1], arr_gps[:, 2])
            ]
        else:
            telemetry.gps_track = [
                (from_ts(t, tz=utc).replace(tzinfo=None), lat, lon)
                for t, lat, lon in zip(arr_gps[:, 0], arr_gps[:, 1], arr_gps[:, 2])
            ]

    # Vector streams: ACCL & GYRO
    arr_accl = arrays.get("accelerometer_samples")
    telemetry.accelerometer_array = arr_accl
    aware_accl = tz_aware.get("accelerometer_samples", True)
    telemetry.accelerometer_samples = LazySampleList(
        arr_accl, is_vector=True, tz_aware=aware_accl,
        audit_label="accelerometer_samples",
    ) if arr_accl is not None else []
    if hasattr(telemetry, "_set_vector_series_from_array"):
        telemetry._set_vector_series_from_array(arr_accl, "accel", tz_aware=aware_accl)
    elif hasattr(telemetry, "_set_vector_series"):
        telemetry._set_vector_series(telemetry.accelerometer_samples, "accel")

    arr_gyro = arrays.get("gyroscope_samples")
    telemetry.gyroscope_array = arr_gyro
    aware_gyro = tz_aware.get("gyroscope_samples", True)
    telemetry.gyroscope_samples = LazySampleList(
        arr_gyro, is_vector=True, tz_aware=aware_gyro,
        audit_label="gyroscope_samples",
    ) if arr_gyro is not None else []
    if hasattr(telemetry, "_set_vector_series_from_array"):
        telemetry._set_vector_series_from_array(arr_gyro, "gyro", tz_aware=aware_gyro)
    elif hasattr(telemetry, "_set_vector_series"):
        telemetry._set_vector_series(telemetry.gyroscope_samples, "gyro")

    t_samples = getattr(telemetry, "temperature_samples", None) or []
    if t_samples:
        print(f"[TMPC Telemetry] temperature_samples={len(t_samples)}", flush=True)


def apply_processed_cache(telemetry: Any, fields: dict[str, Any]) -> None:
    """Apply cached telemetry fields onto a TelemetryDataManager instance."""
    # Fast path: if raw arrays are attached, use direct array materialization
    arrays = fields.get("_arrays")
    meta = fields.get("_meta")
    if arrays is not None and meta is not None:
        apply_processed_cache_arrays(telemetry, arrays, meta)
        return

    def _ensure_tuple_samples(value: Any) -> Any:
        if not isinstance(value, list):
            return value or []
        if not value:
            return []
        if isinstance(value[0], tuple):
            return value
        # Fallback for nested lists from legacy or mock callers
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
            raw_val = fields.get(field)
            setattr(telemetry, field, _ensure_tuple_samples(raw_val))

    if getattr(telemetry, "accelerometer_samples", None):
        if hasattr(telemetry, "_set_vector_series"):
            telemetry._set_vector_series(telemetry.accelerometer_samples, "accel")
    if getattr(telemetry, "gyroscope_samples", None):
        if hasattr(telemetry, "_set_vector_series"):
            telemetry._set_vector_series(telemetry.gyroscope_samples, "gyro")

    t_samples = getattr(telemetry, "temperature_samples", None) or []
    if t_samples:
        print(f"[TMPC Telemetry] temperature_samples={len(t_samples)}", flush=True)
