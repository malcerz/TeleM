"""High-performance native C++ GPMF extraction interface for TeleM.

Extracts GoPro telemetry directly from MP4 container via compiled C++ mp4reader
and gpmf-parser, bypassing FFmpeg raw stream extraction and Python byte decoding.
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

_native_module = None
_native_checked = False

NATIVE_CHANNEL_KEYS = (
    "speed_samples", "alt_samples", "track_samples", "gps_track",
    "accelerometer_samples", "gyroscope_samples", "iso_samples",
    "exposure_samples", "temperature_samples",
)


def native_channel_counts(native_data: dict[str, Any] | None) -> dict[str, int]:
    """Return channel counts without making acceptance depend on GPS."""
    data = native_data or {}
    return {key: len(data.get(key) or []) for key in NATIVE_CHANNEL_KEYS}


def native_channels_used(native_data: dict[str, Any] | None) -> tuple[str, ...]:
    return tuple(key for key, count in native_channel_counts(native_data).items() if count > 0)


def missing_native_channels(native_data: dict[str, Any] | None) -> tuple[str, ...]:
    if not native_data:
        return NATIVE_CHANNEL_KEYS
    present = set(native_data.get("present_channels", []))
    if not present:
        return tuple(key for key, count in native_channel_counts(native_data).items() if count == 0)
    
    # Map GPMF 4CC to our channel keys
    FOURCC_MAP = {
        "GPS5": ("gps_track", "speed_samples", "alt_samples", "track_samples"),
        "ACCL": ("accelerometer_samples",),
        "GYRO": ("gyroscope_samples",),
        "ISOS": ("iso_samples",),
        "SHUT": ("exposure_samples",),
        "CORI": (), # Camera orientation
        "IORI": (), # Image orientation
        "GRAV": (), # Gravity
        "WBAL": (), # White balance
    }
    
    expected_keys = set()
    for fourcc in present:
        if fourcc in FOURCC_MAP:
            expected_keys.update(FOURCC_MAP[fourcc])
            
    # Always expect temperature if any IMU is present
    if "ACCL" in present or "GYRO" in present:
        expected_keys.add("temperature_samples")
        
    return tuple(key for key, count in native_channel_counts(native_data).items() if count == 0 and key in expected_keys)


def native_result_usable(native_data: dict[str, Any] | None) -> bool:
    """A valid IMU-only result is usable even when the GPS channel is empty."""
    return bool(native_data and native_data.get("success") and native_channels_used(native_data))


def merge_native_channel_data(
    native_data: dict[str, Any], fallback_data: dict[str, Any] | None,
) -> dict[str, Any]:
    """Fill only empty native channels from a single legacy-parser pass."""
    merged = dict(native_data)
    for key in NATIVE_CHANNEL_KEYS + ("heading_samples", "slope_samples", "start_dt_utc"):
        if not merged.get(key) and (fallback_data or {}).get(key):
            merged[key] = fallback_data[key]
    return merged


def extract_missing_gpmf_channels(
    records: list[dict], missing: tuple[str, ...],
) -> dict[str, Any]:
    """Extract only missing families from already parsed GPMF records.

    The source is parsed once by the caller. This function deliberately does
    not call the aggregate TelemetryDataManager loader, which would repeat
    ACC/GYRO work for channels already supplied by native code.
    """
    from src.telemetry_extract import (
        extract_accelerometer_samples, extract_altitude_samples,
        extract_exposure_samples, extract_gps_track, extract_gyroscope_samples,
        extract_iso_samples, extract_speed_samples, extract_temperature_samples,
        extract_track_samples,
    )

    extractors = {
        "speed_samples": extract_speed_samples,
        "alt_samples": extract_altitude_samples,
        "track_samples": extract_track_samples,
        "gps_track": extract_gps_track,
        "accelerometer_samples": extract_accelerometer_samples,
        "gyroscope_samples": extract_gyroscope_samples,
        "iso_samples": extract_iso_samples,
        "exposure_samples": extract_exposure_samples,
        "temperature_samples": extract_temperature_samples,
    }
    fallback: dict[str, Any] = {}
    for key in missing:
        fn = extractors.get(key)
        if fn is None:
            continue
        try:
            fallback[key] = fn(records)
        except Exception as exc:
            print(f"[GPMF partial fallback] channel={key} error={exc}", flush=True)

    if "heading_samples" in missing:
        try:
            from src.telemetry_heading import derive_heading_samples
            fallback["heading_samples"] = derive_heading_samples(
                fallback.get("gps_track", []), fallback.get("speed_samples", [])
            )
        except Exception:
            pass
    if "slope_samples" in missing:
        try:
            from src.telemetry_slope import derive_slope_from_streams
            fallback["slope_samples"] = derive_slope_from_streams(
                fallback.get("track_samples", []), fallback.get("alt_samples", [])
            )
        except Exception:
            pass
    return _datetime_samples_to_native(fallback)


def _datetime_samples_to_native(data: dict[str, Any]) -> dict[str, Any]:
    """Convert legacy datetime tuples to the native float-timestamp contract."""
    def ts(value: Any) -> float:
        return value.timestamp() if hasattr(value, "timestamp") else float(value)

    converted = dict(data)
    scalar_keys = {
        "speed_samples", "alt_samples", "track_samples", "iso_samples",
        "exposure_samples", "temperature_samples", "heading_samples", "slope_samples",
    }
    for key in scalar_keys:
        converted[key] = [(ts(item[0]), item[1]) for item in data.get(key, [])]
    converted["gps_track"] = [
        (ts(item[0]), item[1], item[2]) for item in data.get("gps_track", [])
    ]
    for key in ("accelerometer_samples", "gyroscope_samples"):
        converted[key] = [
            (ts(item[0]), tuple(item[1])) for item in data.get(key, [])
        ]
    return converted

def _get_native_module():
    global _native_module, _native_checked
    if _native_checked:
        return _native_module
    _native_checked = True

    # Check native directory
    native_dir = Path(__file__).resolve().parent / "native" / "gpmf"
    if str(native_dir) not in sys.path:
        sys.path.insert(0, str(native_dir))

    try:
        import telem_gpmf_native
        _native_module = telem_gpmf_native
    except ImportError:
        _native_module = None
    return _native_module


def is_native_gpmf_available() -> bool:
    """Return True if native C++ GPMF parser is compiled and loadable."""
    return _get_native_module() is not None


def extract_gpmf_native(video_path: str | Path) -> dict[str, Any] | None:
    """Extract telemetry dictionary directly from MP4 using native C++ parser.

    Returns dict containing canonical telemetry streams, or None on failure.
    """
    mod = _get_native_module()
    if mod is None:
        return None

    path_str = str(video_path)
    try:
        res = mod.extract_gpmf_dict(path_str)
        if res and res.get("success"):
            return res
        return None
    except Exception as exc:
        print(f"[Native GPMF] Error parsing {path_str}: {exc}", flush=True)
        return None


def populate_telemetry_from_native(
    video_path: Path,
    native_data: dict[str, Any],
    manager: Any,
) -> None:
    """Populate a TelemetryDataManager instance with data from native parser."""
    from src.telemetry_heading import derive_heading_samples
    from src.telemetry_slope import derive_slope_from_streams

    def to_dt_list(samples: list) -> list:
        return [(datetime.fromtimestamp(ts, tz=timezone.utc), val) for ts, val in samples]

    def to_dt_track(track: list) -> list:
        return [(datetime.fromtimestamp(ts, tz=timezone.utc), lat, lon) for ts, lat, lon in track]

    manager.speed_samples = to_dt_list(native_data.get("speed_samples", []))
    manager.alt_samples = to_dt_list(native_data.get("alt_samples", []))
    manager.track_samples = to_dt_list(native_data.get("track_samples", []))
    manager.gps_track = to_dt_track(native_data.get("gps_track", []))
    # Keep high-rate IMU in contiguous NumPy/LazySampleList form.  This avoids
    # datetime/tuple materialization for every ACC/GYRO sample on the native path.
    import numpy as np
    from src.telemetry_processed_cache import LazySampleList

    def vector_array(samples: list) -> np.ndarray:
        if not samples:
            return np.zeros((0, 4), dtype=np.float64)
        # Fast flattening with generator, then fromiter, then reshape
        def _flatten():
            for ts, vec in samples:
                yield float(ts)
                yield float(vec[0])
                yield float(vec[1])
                yield float(vec[2])
        return np.fromiter(_flatten(), dtype=np.float64).reshape(-1, 4)

    manager.accelerometer_array = vector_array(native_data.get("accelerometer_samples", []))
    manager.gyroscope_array = vector_array(native_data.get("gyroscope_samples", []))
    manager.accelerometer_samples = LazySampleList(
        manager.accelerometer_array, is_vector=True, tz_aware=True,
        audit_label="native_accelerometer_samples",
    )
    manager.gyroscope_samples = LazySampleList(
        manager.gyroscope_array, is_vector=True, tz_aware=True,
        audit_label="native_gyroscope_samples",
    )
    manager.iso_samples = to_dt_list(native_data.get("iso_samples", []))
    manager.exposure_samples = to_dt_list(native_data.get("exposure_samples", []))
    manager.temperature_samples = to_dt_list(native_data.get("temperature_samples", []))

    start_ts = native_data.get("start_dt_utc", 0.0)
    # Prefer exact resolution from clip if available; avoid pre-GPS-lock default clock (e.g. 2021)
    try:
        from src.multifile import resolve_clip_timestamp
        res = resolve_clip_timestamp(video_path)
        if res.absolute_start_dt is not None:
            manager.start_dt_utc = res.absolute_start_dt.replace(tzinfo=timezone.utc) if res.absolute_start_dt.tzinfo is None else res.absolute_start_dt
        elif start_ts > 0.0:
            manager.start_dt_utc = datetime.fromtimestamp(start_ts, tz=timezone.utc)
    except Exception:
        if start_ts > 0.0:
            manager.start_dt_utc = datetime.fromtimestamp(start_ts, tz=timezone.utc)

    # Standard post-processing (smoothing, vector components, derived heading/slope)
    manager.smooth_all_gpmf()
    manager._set_vector_series_from_array(manager.accelerometer_array, "accel")
    manager._set_vector_series_from_array(manager.gyroscope_array, "gyro")
    manager.heading_samples = derive_heading_samples(manager.gps_track, manager.speed_samples)
    manager.slope_samples = derive_slope_from_streams(manager.track_samples, manager.alt_samples)
    if manager.temperature_samples:
        print(f"[TMPC Telemetry] temperature_samples={len(manager.temperature_samples)}", flush=True)
