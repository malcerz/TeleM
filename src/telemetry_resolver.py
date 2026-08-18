"""Shared source-aware telemetry resolution primitives.

This module deliberately contains no fallback between telemetry sources.  A
caller must choose ``gpmf``, ``fit`` or ``gpx`` explicitly; an empty result is
returned when that source has no samples.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


SOURCE_ALIASES: dict[str, dict[str, tuple[str, ...]]] = {
    "fit": {
        "power": ("power", "curVpower"),
        "hr": ("hr", "heart_rate"),
        "cad": ("cad", "cadence"),
        "atemp": ("atemp", "temperature"),
        "battery": ("battery", "battery_soc"),
    },
    "gpx": {
        "power": ("power",),
        "hr": ("hr",),
        "cad": ("cad",),
        "atemp": ("atemp",),
        "battery": ("battery",),
    },
}

_GPMF_ATTRS = {
    "speed": "speed_samples",
    "alt": "alt_samples",
    "altitude": "alt_samples",
    "dist": "track_samples",
    "track": "track_samples",
    "iso": "iso_samples",
    "exposure": "exposure_samples",
    "temperature": "temperature_samples",
    "accel_x": "accel_x_samples",
    "accel_y": "accel_y_samples",
    "accel_z": "accel_z_samples",
    "accel_magnitude": "accel_magnitude_samples",
    "gyro_x": "gyro_x_samples",
    "gyro_y": "gyro_y_samples",
    "gyro_z": "gyro_z_samples",
    "gyro_magnitude": "gyro_magnitude_samples",
}

_GPX_ATTRS = {
    "speed": "gpx_speed_samples",
    "alt": "gpx_alt_samples",
    "altitude": "gpx_alt_samples",
    "dist": "gpx_track_samples",
    "track": "gpx_track_samples",
    "power": "gpx_power_samples",
    "hr": "gpx_hr_samples",
    "cad": "gpx_cad_samples",
    "atemp": "gpx_atemp_samples",
    "battery": "gpx_battery_samples",
}


def resolve_samples_from_sources(
    logical_field: str,
    source: str,
    *,
    gpmf: Any,
    fit_data: Mapping[str, list] | None = None,
    gpx: Any = None,
) -> list:
    """Return samples for exactly ``source`` and ``logical_field``.

    ``gpmf``, ``fit_data`` and ``gpx`` are intentionally duck-typed so the
    same contract can be used by the GUI manager and FFmpeg worker cache.
    """
    source = source or "gpmf"
    if source == "gpmf":
        attr = _GPMF_ATTRS.get(logical_field)
        return list(getattr(gpmf, attr, []) or []) if attr else []

    if source == "fit":
        data = fit_data or {}
        names = SOURCE_ALIASES["fit"].get(logical_field, (logical_field,))
        for name in names:
            samples = data.get(name, []) or []
            if samples:
                return list(samples)
        return []

    if source == "gpx":
        attr = _GPX_ATTRS.get(logical_field)
        return list(getattr(gpx, attr, []) or []) if attr else []

    return []


def resolve_field_from_sources(
    logical_field: str,
    source: str,
    *,
    gpmf: Any,
    fit_data: Mapping[str, list] | None = None,
    gpx: Any = None,
) -> list:
    """Named alias for the sample resolver used by value and history paths."""
    return resolve_samples_from_sources(
        logical_field, source, gpmf=gpmf, fit_data=fit_data, gpx=gpx
    )
