"""Shared source-aware telemetry resolution primitives.

This module deliberately contains no fallback between telemetry sources.  A
caller must choose ``gpmf``, ``fit`` or ``gpx`` explicitly; an empty result is
returned when that source has no samples.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any


SOURCE_ALIASES: dict[str, dict[str, tuple[str, ...]]] = {
    "fit": {
        # FIT distance is the canonical cumulative activity stream.  ``track``
        # remains the GPS-derived fallback for files without that FIT field.
        "distance": ("distance", "track"),
        "power": ("power", "curVpower"),
        "hr": ("hr", "heart_rate"),
        "cad": ("cad", "cadence"),
        "atemp": ("atemp", "temperature", "garmin_temperature"),
        "battery": ("battery", "battery_soc", "garmin_battery_percent", "battery_pct"),
        "garmin_battery_voltage": ("garmin_battery_voltage", "battery_voltage"),
        "garmin_battery_percent": ("garmin_battery_percent", "battery_level", "battery_pct", "battery"),
        "garmin_temperature": ("garmin_temperature", "device_temperature", "temperature"),
        "heading": ("heading",),
        "slope": ("slope",),
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
    "distance": "track_samples",
    "track": "track_samples",
    "iso": "iso_samples",
    "exposure": "exposure_samples",
    "temperature": "temperature_samples",
    "heading": "heading_samples",
    "slope": "slope_samples",
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
    "distance": "gpx_track_samples",
    "track": "gpx_track_samples",
    "power": "gpx_power_samples",
    "hr": "gpx_hr_samples",
    "cad": "gpx_cad_samples",
    "atemp": "gpx_atemp_samples",
    "battery": "gpx_battery_samples",
    "heading": "gpx_heading_samples",
    "slope": "gpx_slope_samples",
}


def _is_usable_cumulative_distance(samples: list) -> bool:
    """Return whether *samples* can represent an activity-global distance."""
    if len(samples) < 2:
        return False
    previous = None
    try:
        for _timestamp, value in samples:
            current = float(value)
            if not math.isfinite(current):
                return False
            if previous is not None and current < previous - 1e-6:
                return False
            previous = current
    except (TypeError, ValueError):
        return False
    return True


def resolve_distance_samples(
    source: str,
    *,
    gpmf_track: list | None = None,
    fit_data: Mapping[str, list] | None = None,
    gpx_track: list | None = None,
) -> list:
    """Return the one canonical cumulative-distance stream for ``source``.

    FIT's recorded ``distance`` field is preferred when it is a usable
    monotonic stream.  The GPS-derived FIT ``track`` is an explicit fallback,
    not a value to combine with the recorded field.  All returned values stay
    in the internal unit used by the telemetry pipeline: metres.
    """
    source = source or "gpmf"
    if source == "fit":
        data = fit_data or {}
        recorded = list(data.get("distance", []) or [])
        if _is_usable_cumulative_distance(recorded):
            return recorded
        return list(data.get("track", []) or [])
    if source == "gpx":
        return list(gpx_track or [])
    return list(gpmf_track or [])


def distance_max_m(samples: list | None) -> float | None:
    """Return the maximum valid distance in metres from one selected stream."""
    if not samples:
        return None
    try:
        values = [float(value) for _timestamp, value in samples]
        return max(values) if values else None
    except (TypeError, ValueError):
        return None


def build_activity_range_cache(
    layout: Mapping[str, Any], *, speed_samples: list | None = None,
    track_samples: list | None = None, alt_samples: list | None = None,
    gpx_speed_samples: list | None = None,
    gpx_track_samples: list | None = None,
    gpx_alt_samples: list | None = None,
    fit_data: Mapping[str, list] | None = None,
) -> dict[str, float | None]:
    """Build source-exact HUD ranges over the whole loaded activity."""
    indicators = (layout or {}).get("indicators", {})
    fit = fit_data or {}

    def _selected_indicator(*keys: str) -> Mapping[str, Any]:
        configured = [indicators[key] for key in keys if key in indicators]
        return next(
            (cfg for cfg in configured if cfg.get("enabled", True)),
            configured[0] if configured else {},
        )

    dist_ind = _selected_indicator(
        "dist_visual", "dist_text", "fit_distance_text"
    )
    dist_source = dist_ind.get(
        "source", "fit" if "fit_distance_text" in indicators else "gpmf"
    )
    distance = resolve_distance_samples(
        dist_source, gpmf_track=track_samples, fit_data=fit,
        gpx_track=gpx_track_samples,
    )
    speed_ind = _selected_indicator(
        "speed_visual", "speed_text", "fit_speed_text",
        "fit_enhanced_speed_text",
    )
    speed_source = speed_ind.get(
        "source", "fit" if (
            "fit_speed_text" in indicators
            or "fit_enhanced_speed_text" in indicators
        ) else "gpmf",
    )
    speed = (
        gpx_speed_samples if speed_source == "gpx"
        else fit.get("speed", []) if speed_source == "fit"
        else speed_samples
    ) or []
    alt_ind = _selected_indicator(
        "alt_visual", "alt_text", "fit_altitude_text",
        "fit_enhanced_altitude_text",
    )
    alt_source = alt_ind.get(
        "source", "fit" if (
            "fit_altitude_text" in indicators
            or "fit_enhanced_altitude_text" in indicators
        ) else "gpmf",
    )
    altitude = (
        gpx_alt_samples if alt_source == "gpx"
        else fit.get("alt", []) if alt_source == "fit"
        else alt_samples
    ) or []

    def _values(samples: list) -> list[float]:
        values: list[float] = []
        for _timestamp, value in samples:
            try:
                number = float(value)
            except (TypeError, ValueError):
                continue
            if math.isfinite(number):
                values.append(number)
        return values

    speed_values = _values(list(speed))
    altitude_values = _values(list(altitude))
    return {
        "max_distance_m": distance_max_m(distance),
        "max_speed_kmh": max(speed_values) if speed_values else None,
        "min_alt": min(altitude_values) if altitude_values else None,
        "max_alt": max(altitude_values) if altitude_values else None,
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
    if logical_field == "distance":
        return resolve_distance_samples(
            source,
            gpmf_track=list(getattr(gpmf, "track_samples", []) or []),
            fit_data=fit_data,
            gpx_track=list(getattr(gpx, "gpx_track_samples", []) or []),
        )
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
