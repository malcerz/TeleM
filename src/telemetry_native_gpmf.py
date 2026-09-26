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
    manager.accelerometer_samples = to_dt_list(native_data.get("accelerometer_samples", []))
    manager.gyroscope_samples = to_dt_list(native_data.get("gyroscope_samples", []))
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
    manager._set_vector_series(manager.accelerometer_samples, "accel")
    manager._set_vector_series(manager.gyroscope_samples, "gyro")
    manager.heading_samples = derive_heading_samples(manager.gps_track, manager.speed_samples)
    manager.slope_samples = derive_slope_from_streams(manager.track_samples, manager.alt_samples)
    if manager.temperature_samples:
        print(f"[TMPC Telemetry] temperature_samples={len(manager.temperature_samples)}", flush=True)
