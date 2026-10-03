"""Central indicator telemetry data availability engine.

Determines whether each indicator in a layout has an available project-level
data source, distinguishing between:
  Case A: Data source does not exist in the project at all -> HIDE completely
          (no box, no label, no unit, no icon, no '--', no empty chart).
  Case B: Data source exists in the project, but is temporarily None in a frame
          -> SHOW with '--' placeholder.

This module guarantees parity across GUI preview, CPU final render, and native
GPU exporters (AMD, Intel, NVIDIA).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Mapping

from src.telemetry_resolver import (
    canonical_telemetry_field,
    resolve_distance_samples,
    SOURCE_ALIASES,
)


def _has_samples(val: Any) -> bool:
    """Return True if val represents a non-empty telemetry series or array."""
    if val is None:
        return False
    if hasattr(val, "__len__"):
        return len(val) > 0
    if hasattr(val, "shape"):
        return getattr(val, "size", 0) > 0
    return bool(val)


def _has_track(val: Any) -> bool:
    """Return True if val represents a valid GPS track with at least 2 points."""
    if val is None:
        return False
    if hasattr(val, "__len__"):
        return len(val) >= 2
    return False


def _extract_telemetry_sources(telemetry: Any, kwargs: dict[str, Any]) -> dict[str, Any]:
    """Consolidate data sources from either a TelemetryDataManager or explicit kwargs."""
    data: dict[str, Any] = {}

    keys = (
        "speed_samples", "track_samples", "alt_samples",
        "iso_samples", "exposure_samples", "temperature_samples",
        "heading_samples", "slope_samples",
        "accelerometer_samples", "gyroscope_samples", "quaternion_samples",
        "camera_metadata", "gps_track",
        "gpx_speed_samples", "gpx_track_samples", "gpx_alt_samples",
        "gpx_power_samples", "gpx_atemp_samples", "gpx_hr_samples",
        "gpx_cad_samples", "gpx_battery_samples", "gpx_heading_samples",
        "gpx_slope_samples", "gpx_gps_track",
        "fit_data", "fit_gps_track", "available_fit_fields",
        "video_duration_s", "start_dt_utc", "video_timeline",
        "accelerometer_array", "gyroscope_array", "_lean_roll_cache",
        "accel_x_samples", "gyro_x_samples",
    )

    for k in keys:
        if k in kwargs and kwargs[k] is not None:
            data[k] = kwargs[k]
        elif telemetry is not None:
            val = getattr(telemetry, k, None)
            if val is not None:
                data[k] = val

    # Common aliases / fallbacks
    if "video_duration_s" not in data and telemetry is not None:
        data["video_duration_s"] = getattr(telemetry, "video_duration", 0.0)

    return data


def _check_source_for_field(field: str, source: str, data: dict[str, Any]) -> tuple[bool, str]:
    """Check if *source* provides valid data for *field*."""
    field_lower = field.lower()
    source_lower = source.lower()

    if source_lower == "gpmf":
        if field_lower in ("speed", "enhanced_speed", "ground_speed"):
            if _has_samples(data.get("speed_samples")):
                return True, "source=gpmf"
            return False, "gpmf has no speed samples"
        if field_lower in ("distance", "dist", "track"):
            if _has_samples(data.get("track_samples")):
                return True, "source=gpmf"
            return False, "gpmf has no distance samples"
        if field_lower in ("alt", "altitude", "enhanced_altitude"):
            if _has_samples(data.get("alt_samples")):
                return True, "source=gpmf"
            return False, "gpmf has no altitude samples"
        if field_lower == "iso":
            if _has_samples(data.get("iso_samples")):
                return True, "source=gpmf"
            cm = data.get("camera_metadata")
            if isinstance(cm, dict) and cm.get("iso"):
                return True, "source=camera"
            return False, "gpmf has no ISO samples"
        if field_lower == "exposure":
            if _has_samples(data.get("exposure_samples")):
                return True, "source=gpmf"
            cm = data.get("camera_metadata")
            if isinstance(cm, dict) and cm.get("exposure"):
                return True, "source=camera"
            return False, "gpmf has no exposure samples"
        if field_lower in ("temp", "atemp", "temperature", "garmin_temperature"):
            if _has_samples(data.get("temperature_samples")):
                return True, "source=gpmf"
            return False, "gpmf has no temperature samples"
        if field_lower in ("heading", "compass"):
            if _has_samples(data.get("heading_samples")) or _has_track(data.get("gps_track")):
                return True, "source=gpmf"
            return False, "gpmf has no heading or GPS track"
        if field_lower == "slope":
            if _has_samples(data.get("slope_samples")) or (
                _has_track(data.get("gps_track")) and _has_samples(data.get("alt_samples"))
            ):
                return True, "source=gpmf"
            return False, "gpmf has no slope data"
        if field_lower in ("hr", "heart_rate", "cad", "cadence", "power", "battery"):
            return False, f"gpmf does not provide {field}"
        return False, f"gpmf has no stream for '{field}'"

    if source_lower == "fit":
        fit_d = data.get("fit_data")
        if not fit_d or not isinstance(fit_d, (dict, Mapping)):
            return False, "no FIT dataset loaded"

        if field_lower in ("speed", "enhanced_speed", "ground_speed"):
            if _has_samples(fit_d.get("enhanced_speed")) or _has_samples(fit_d.get("speed")):
                return True, "source=fit"
            return False, "fit has no speed samples"
        if field_lower in ("distance", "dist", "track"):
            fit_dist = resolve_distance_samples("fit", fit_data=fit_d)
            if _has_samples(fit_dist):
                return True, "source=fit"
            return False, "fit has no distance samples"
        if field_lower in ("alt", "altitude", "enhanced_altitude"):
            if _has_samples(fit_d.get("enhanced_altitude")) or _has_samples(fit_d.get("alt")) or _has_samples(fit_d.get("altitude")):
                return True, "source=fit"
            return False, "fit has no altitude samples"
        if field_lower in ("hr", "heart_rate"):
            if _has_samples(fit_d.get("hr")) or _has_samples(fit_d.get("heart_rate")):
                return True, "source=fit"
            return False, "fit has no HR samples"
        if field_lower in ("cad", "cadence"):
            if _has_samples(fit_d.get("cad")) or _has_samples(fit_d.get("cadence")):
                return True, "source=fit"
            return False, "fit has no cadence samples"
        if field_lower in ("power", "curvpower", "curv_power"):
            power_aliases = ("power", "curVpower", "curVPower", "curvpower")
            if any(_has_samples(fit_d.get(k)) for k in power_aliases):
                return True, "source=fit"
            return False, "fit has no power samples"
        if field_lower in ("battery", "battery_soc", "garmin_battery_percent", "battery_pct", "battery_level", "garmin_battery_voltage", "battery_voltage"):
            bat_aliases = ("battery", "battery_soc", "garmin_battery_percent", "battery_pct", "battery_level", "garmin_battery_voltage", "battery_voltage")
            if any(_has_samples(fit_d.get(k)) for k in bat_aliases):
                return True, "source=fit"
            return False, "fit has no battery samples"
        if field_lower in ("temp", "atemp", "temperature", "garmin_temperature"):
            temp_aliases = ("atemp", "temperature", "garmin_temperature", "device_temperature")
            if any(_has_samples(fit_d.get(k)) for k in temp_aliases):
                return True, "source=fit"
            return False, "fit has no temperature samples"
        if field_lower in ("heading", "compass"):
            if _has_samples(fit_d.get("heading")) or _has_track(data.get("fit_gps_track")):
                return True, "source=fit"
            return False, "fit has no heading or GPS track"
        if field_lower == "slope":
            if _has_samples(fit_d.get("slope")):
                return True, "source=fit"
            return False, "fit has no slope data"

        # Check aliases from SOURCE_ALIASES
        aliases = SOURCE_ALIASES.get("fit", {}).get(field_lower, (field_lower,))
        for name in aliases:
            if _has_samples(fit_d.get(name)):
                return True, "source=fit"
        lower_map = {str(k).lower(): k for k in fit_d.keys()}
        for name in aliases:
            mk = lower_map.get(str(name).lower())
            if mk and _has_samples(fit_d.get(mk)):
                return True, "source=fit"
        return False, f"fit has no field '{field}'"

    if source_lower == "gpx":
        if field_lower in ("speed", "enhanced_speed", "ground_speed"):
            if _has_samples(data.get("gpx_speed_samples")):
                return True, "source=gpx"
            return False, "gpx has no speed samples"
        if field_lower in ("distance", "dist", "track"):
            if _has_samples(data.get("gpx_track_samples")):
                return True, "source=gpx"
            return False, "gpx has no distance samples"
        if field_lower in ("alt", "altitude", "enhanced_altitude"):
            if _has_samples(data.get("gpx_alt_samples")):
                return True, "source=gpx"
            return False, "gpx has no altitude samples"
        if field_lower in ("hr", "heart_rate"):
            if _has_samples(data.get("gpx_hr_samples")):
                return True, "source=gpx"
            return False, "gpx has no HR samples"
        if field_lower in ("cad", "cadence"):
            if _has_samples(data.get("gpx_cad_samples")):
                return True, "source=gpx"
            return False, "gpx has no cadence samples"
        if field_lower in ("power", "curvpower", "curv_power"):
            if _has_samples(data.get("gpx_power_samples")):
                return True, "source=gpx"
            return False, "gpx has no power samples"
        if field_lower in ("battery", "battery_soc", "battery_pct"):
            if _has_samples(data.get("gpx_battery_samples")):
                return True, "source=gpx"
            return False, "gpx has no battery samples"
        if field_lower in ("temp", "atemp", "temperature"):
            if _has_samples(data.get("gpx_atemp_samples")):
                return True, "source=gpx"
            return False, "gpx has no temperature samples"
        if field_lower in ("heading", "compass"):
            if _has_samples(data.get("gpx_heading_samples")) or _has_track(data.get("gpx_gps_track")):
                return True, "source=gpx"
            return False, "gpx has no heading or GPS track"
        if field_lower == "slope":
            if _has_samples(data.get("gpx_slope_samples")):
                return True, "source=gpx"
            return False, "gpx has no slope data"
        return False, f"gpx has no stream for '{field}'"

    if source_lower == "camera":
        cm = data.get("camera_metadata")
        if isinstance(cm, dict) and field_lower in cm and cm[field_lower] is not None:
            return True, "source=camera"
        return False, f"camera metadata has no field '{field}'"

    return False, f"unrecognized source '{source}'"


def indicator_data_available(
    indicator_key: str,
    ind_cfg: Mapping[str, Any],
    telemetry: Any = None,
    **kwargs: Any,
) -> tuple[bool, str]:
    """Return (available, reason) for a single indicator in the current project.

    Does NOT inspect single-frame values (no frame-level None check).
    Instead answers: 'Does a valid data source exist in the active project?'
    """
    key = str(indicator_key).strip()
    cfg = dict(ind_cfg) if ind_cfg else {}
    data = _extract_telemetry_sources(telemetry, kwargs)

    # ── 1. Time display ───────────────────────────────────────────────
    if key == "time_display":
        dur = float(data.get("video_duration_s") or 0.0)
        has_time = dur > 0.0 or data.get("start_dt_utc") is not None or data.get("video_timeline") is not None
        if has_time:
            return True, "project timeline available"
        return False, "no project timeline or duration"

    # ── 2. Track Map ──────────────────────────────────────────────────
    if key == "track_map":
        gps_src = str(cfg.get("gps_source") or cfg.get("source") or "auto").strip().lower()
        if gps_src == "fit":
            if _has_track(data.get("fit_gps_track")) or (_has_track(data.get("gps_track")) and bool(data.get("fit_data"))):
                return True, "source=fit"
            return False, "no GPS track for configured source 'fit'"
        if gps_src == "gpmf":
            if _has_track(data.get("gps_track")):
                return True, "source=gpmf"
            return False, "no GPS track for configured source 'gpmf'"
        if gps_src == "gpx":
            if _has_track(data.get("gpx_gps_track")) or (_has_track(data.get("gps_track")) and bool(data.get("gpx_track_samples"))):
                return True, "source=gpx"
            return False, "no GPS track for configured source 'gpx'"
        # Auto candidates in priority: fit -> gpmf -> gpx
        if _has_track(data.get("fit_gps_track")):
            return True, "source=fit"
        if _has_track(data.get("gps_track")):
            return True, "source=gpmf"
        if _has_track(data.get("gpx_gps_track")):
            return True, "source=gpx"
        if _has_track(data.get("gps_track")):
            return True, "source=gps_track"
        return False, "no source available (configured=auto, candidates=[fit, gpmf, gpx])"

    # ── 3. Lean indicator ─────────────────────────────────────────────
    if key == "lean_indicator":
        lsrc = str(cfg.get("source", "gyro")).strip().lower()
        if lsrc == "grade":
            slope_src = str(cfg.get("slope_source", "auto")).strip().lower()
            if slope_src == "gpmf":
                if _has_samples(data.get("slope_samples")) or (_has_track(data.get("gps_track")) and _has_samples(data.get("alt_samples"))):
                    return True, "source=grade (gpmf)"
                return False, "configured slope source 'gpmf' has no slope data"
            if slope_src == "fit":
                fit_d = data.get("fit_data")
                if isinstance(fit_d, (dict, Mapping)) and _has_samples(fit_d.get("slope")):
                    return True, "source=grade (fit)"
                return False, "configured slope source 'fit' has no slope data"
            if slope_src == "gpx":
                if _has_samples(data.get("gpx_slope_samples")):
                    return True, "source=grade (gpx)"
                return False, "configured slope source 'gpx' has no slope data"
            # Auto: gpmf -> fit -> gpx
            if _has_samples(data.get("slope_samples")) or (_has_track(data.get("gps_track")) and _has_samples(data.get("alt_samples"))):
                return True, "source=grade (gpmf)"
            fit_d = data.get("fit_data")
            if isinstance(fit_d, (dict, Mapping)) and _has_samples(fit_d.get("slope")):
                return True, "source=grade (fit)"
            if _has_samples(data.get("gpx_slope_samples")):
                return True, "source=grade (gpx)"
            return False, "no source available (configured=auto, candidates=[gpmf, fit, gpx])"
        else:
            # Gyro / IMU
            has_imu = (
                _has_samples(data.get("gyroscope_samples"))
                or _has_samples(data.get("accelerometer_samples"))
                or _has_samples(data.get("quaternion_samples"))
                or _has_samples(data.get("gyroscope_array"))
                or _has_samples(data.get("accelerometer_array"))
                or bool(data.get("_lean_roll_cache"))
            )
            if has_imu:
                return True, "source=imu"
            return False, "no IMU / gyro / accelerometer data available"

    # ── 4. IMU Raw Scalar Fields ──────────────────────────────────────
    if key.startswith("accel_") and key.endswith("_text"):
        has_accel = (
            _has_samples(data.get("accelerometer_samples"))
            or _has_samples(data.get("accelerometer_array"))
            or _has_samples(data.get("accel_x_samples"))
        )
        if has_accel:
            return True, "source=imu"
        return False, "no accelerometer data available"

    if key.startswith("gyro_") and key.endswith("_text"):
        has_gyro = (
            _has_samples(data.get("gyroscope_samples"))
            or _has_samples(data.get("gyroscope_array"))
            or _has_samples(data.get("gyro_x_samples"))
        )
        if has_gyro:
            return True, "source=imu"
        return False, "no gyroscope data available"

    # ── 5. Dynamic FIT Fields (fit_*_text) ─────────────────────────────
    if key.startswith("fit_") and key.endswith("_text"):
        field = canonical_telemetry_field(key)
        fit_d = data.get("fit_data")
        if not fit_d or not isinstance(fit_d, (dict, Mapping)):
            return False, "no FIT dataset loaded"

        avail_fit = data.get("available_fit_fields")
        if avail_fit is not None:
            avail_set = {str(x).lower() for x in avail_fit}
            if field.lower() not in avail_set and key.lower() not in avail_set:
                return False, f"field '{field}' not in discovered FIT fields"

        aliases = SOURCE_ALIASES.get("fit", {}).get(field, (field,))
        for name in aliases:
            if _has_samples(fit_d.get(name)):
                return True, f"source=fit (field={name})"
        lower_map = {str(k).lower(): k for k in fit_d.keys()}
        for name in aliases:
            mk = lower_map.get(str(name).lower())
            if mk and _has_samples(fit_d.get(mk)):
                return True, f"source=fit (field={mk})"
        return False, f"no FIT samples for field '{field}'"

    # ── 6. Standard / Configured Indicators ────────────────────────────
    field_name = canonical_telemetry_field(cfg.get("field") or key)
    raw_source = cfg.get("source")
    source = str(raw_source).strip().lower() if raw_source is not None else ""
    is_auto = source in ("", "auto", "default", "none")

    if not is_auto:
        # User explicitly chose this source -> must check ONLY this source!
        ok, reason = _check_source_for_field(field_name, source, data)
        if ok:
            return True, reason
        return False, f"no source available (configured={source})"

    # Auto source resolution: check candidate sources in order
    if field_name in ("hr", "heart_rate", "cad", "cadence", "power"):
        candidates = ("fit", "gpx")
    elif field_name in ("battery", "battery_soc", "garmin_battery_percent", "battery_pct"):
        candidates = ("fit", "gpx")
    elif field_name in ("iso", "exposure"):
        candidates = ("gpmf", "camera")
    elif field_name in ("dist", "distance", "track"):
        # For distance, FIT cumulative is preferred canonical, followed by GPMF, then GPX
        candidates = ("fit", "gpmf", "gpx")
    elif field_name in ("speed", "alt", "temp", "atemp", "temperature", "heading", "compass", "slope"):
        candidates = ("gpmf", "fit", "gpx")
    else:
        candidates = ("fit", "gpmf", "gpx", "camera")

    for cand in candidates:
        ok, _ = _check_source_for_field(field_name, cand, data)
        if ok:
            return True, f"source={cand}"

    return False, f"no source available (configured=auto, candidates={list(candidates)})"


def compute_indicator_availability(
    layout: Mapping[str, Any],
    telemetry: Any = None,
    **kwargs: Any,
) -> dict[str, tuple[bool, str]]:
    """Compute (available, reason) for all indicators in layout."""
    indicators = layout.get("indicators", {}) if layout else {}
    results: dict[str, tuple[bool, str]] = {}

    for key, ind_cfg in indicators.items():
        if not isinstance(ind_cfg, (dict, Mapping)):
            continue
        results[key] = indicator_data_available(key, ind_cfg, telemetry=telemetry, **kwargs)

    return results


def get_effective_indicator_availability(
    layout: Mapping[str, Any],
    telemetry: Any = None,
    **kwargs: Any,
) -> dict[str, bool]:
    """Return {indicator_key: bool} indicating project-level data availability."""
    computed = compute_indicator_availability(layout, telemetry=telemetry, **kwargs)
    return {k: res[0] for k, res in computed.items()}


_LAST_LOGGED_AVAILABILITY: tuple[Any, ...] | None = None


def log_indicator_availability(
    availability_results: Mapping[str, tuple[bool, str]],
    force: bool = False,
) -> None:
    """Print the single diagnostic log for indicator availability if state changed."""
    global _LAST_LOGGED_AVAILABILITY

    # Deduplicate against previous log
    sorted_items = tuple(sorted((k, v[0], v[1]) for k, v in availability_results.items()))
    if not force and sorted_items == _LAST_LOGGED_AVAILABILITY:
        return
    _LAST_LOGGED_AVAILABILITY = sorted_items

    for key, (avail, reason) in sorted(availability_results.items()):
        print(f"[INDICATOR AVAILABILITY] key={key} visible={avail} reason=\"{reason}\"", flush=True)
