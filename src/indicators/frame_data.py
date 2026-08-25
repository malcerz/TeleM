"""Shared overlay frame data preparation.

Extracted from ``overlay_renderer.py``.

Consolidates the data-preparation logic that was previously duplicated
between ``_render_preview`` (controller.py) and ``render_overlay_frame``
(ffmpeg_pipeline.py).  Both callers invoke this single function.
"""

from __future__ import annotations

import time
from datetime import datetime, timedelta
from typing import Any, Callable, Optional

from src.indicators.profiling import get_overlay_profiler


_STANDARD_RESOLVE_CONSUMERS: dict[str, str] = {
    "power_text": "power",
    "atemp_text": "atemp",
    "hr_text": "hr",
    "cad_text": "cad",
    "battery_text": "battery",
}


def build_active_fit_field_plan(
    layout: dict[str, Any], discovered_fit_fields: Any
) -> dict[str, list[str]]:
    """Build immutable per-export telemetry dependencies from a HUD layout.

    Dynamic FIT indicators encode their selected field in the stable GUI key
    ``fit_{field_name}_text``.  The form (text/chart/gauge/...) does not alter
    that dependency.  Exact field names are collected in sets so multiple
    consumers can never cause duplicate per-frame resolution.
    """
    discovered = {str(field) for field in (discovered_fit_fields or [])}
    active_fit: set[str] = set()
    active_standard: set[str] = set()

    for key, config in layout.get("indicators", {}).items():
        if not isinstance(config, dict) or not config.get("enabled", True):
            continue
        if key.startswith("fit_") and key.endswith("_text"):
            field_name = key[4:-5]
            if field_name:
                active_fit.add(field_name)
            continue
        standard_field = _STANDARD_RESOLVE_CONSUMERS.get(key)
        if standard_field:
            active_standard.add(standard_field)

    return {
        "discovered_fit_fields": sorted(discovered),
        "active_fit_fields": sorted(active_fit),
        "inactive_fit_fields": sorted(discovered - active_fit),
        "active_fit_fields_missing_samples": sorted(active_fit - discovered),
        "active_standard_resolve_fields": sorted(active_standard),
        "unique_resolve_fields": sorted(active_fit | active_standard),
    }


def prepare_overlay_frame_data(
    *,
    layout: dict[str, Any],
    target_dt: datetime,
    tz_offset_hours: float,
    start_dt_utc: Optional[datetime],
    speed_samples: list,
    track_samples: list,
    alt_samples: list,
    iso_samples: Optional[list] = None,
    exposure_samples: Optional[list] = None,
    temperature_samples: Optional[list] = None,
    gpx_speed_samples: Optional[list] = None,
    gpx_track_samples: Optional[list] = None,
    gpx_alt_samples: Optional[list] = None,
    gpx_power_samples: Optional[list] = None,
    gpx_atemp_samples: Optional[list] = None,
    gpx_hr_samples: Optional[list] = None,
    gpx_cad_samples: Optional[list] = None,
    fit_data: Optional[dict[str, list]] = None,
    gps_track: Optional[list] = None,
    total_frames: int = 1,
    current_index: int = 0,
    chart_data: Optional[dict[str, list[float]]] = None,
    extra_field_keys: Optional[list[str]] = None,
    resolve_cache_value: Optional[Callable] = None,
    _range_cache: Optional[dict] = None,
    fit_field_plan: Optional[dict[str, list[str]]] = None,
    resolve_stats: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Prepare all values needed by ``compose_overlay`` for a single frame.

    This function consolidates the data-preparation logic that was previously
    duplicated between ``_render_preview`` (controller.py) and
    ``render_overlay_frame`` (ffmpeg_pipeline.py).  Both callers now invoke
    this single function, eliminating any future drift.

    Returns a dict suitable for ``**kwargs`` to ``compose_overlay``.
    """
    profiler = get_overlay_profiler()
    from src.telemetry_extract import (
        interpolate_speed, interpolate_distance, interpolate_altitude,
        interpolate_iso, interpolate_exposure, interpolate_temperature,
    )

    # ── Time strings ──────────────────────────────────────────────────
    section_started = time.perf_counter()
    local_dt = target_dt + timedelta(hours=tz_offset_hours)
    date_text = local_dt.strftime("%Y-%m-%d")
    time_text = local_dt.strftime("%H:%M:%S")
    profiler.record(
        "telemetry.date_time",
        (time.perf_counter() - section_started) * 1000.0,
    )

    # ── Per-source indicator values (speed / dist / alt) ──────────────
    section_started = time.perf_counter()
    indicator_values: dict[str, float] = {}
    for ind_key in ("speed_visual", "speed_text", "dist_visual", "dist_text",
                    "alt_visual", "alt_text"):
        ind_cfg = layout.get("indicators", {}).get(ind_key, {})
        if not ind_cfg.get("enabled", True):
            continue
        src = ind_cfg.get("source", "gpmf")
        gpx_spd = gpx_speed_samples or []
        gpx_trk = gpx_track_samples or []
        gpx_alt = gpx_alt_samples or []
        fit_spd = (fit_data or {}).get("speed", [])
        fit_trk = (fit_data or {}).get("track", [])
        fit_alt = (fit_data or {}).get("alt", [])
        if src == "gpx":
            spd_s = gpx_spd or speed_samples
            trk_s = gpx_trk or track_samples
            alt_s = gpx_alt or alt_samples
        elif src == "fit":
            spd_s = fit_spd or speed_samples
            trk_s = fit_trk or track_samples
            alt_s = fit_alt or alt_samples
        else:
            spd_s, trk_s, alt_s = speed_samples, track_samples, alt_samples
        if ind_key in ("speed_visual", "speed_text"):
            indicator_values[ind_key] = interpolate_speed(spd_s, target_dt)
        elif ind_key in ("dist_visual", "dist_text"):
            indicator_values[ind_key] = interpolate_distance(trk_s, target_dt)
        elif ind_key in ("alt_visual", "alt_text"):
            indicator_values[ind_key] = interpolate_altitude(alt_s, target_dt)

    # ── Primary values ────────────────────────────────────────────────
    speed_value = indicator_values.get(
        "speed_visual", interpolate_speed(speed_samples, target_dt))
    distance_m = indicator_values.get(
        "dist_visual", interpolate_distance(track_samples, target_dt))
    alt_value = indicator_values.get(
        "alt_visual", interpolate_altitude(alt_samples, target_dt))

    iso_value = interpolate_iso(iso_samples or [], target_dt)
    exposure_value = interpolate_exposure(exposure_samples or [], target_dt)
    temp_value = interpolate_temperature(temperature_samples or [], target_dt)
    profiler.record(
        "telemetry.interpolation_lookups",
        (time.perf_counter() - section_started) * 1000.0,
    )

    # ── max_distance_m (per source) ───────────────────────────────────
    section_started = time.perf_counter()
    if _range_cache and "max_distance_m" in _range_cache:
        max_distance_m = _range_cache["max_distance_m"]
    else:
        max_distance_m = None
        dist_src = layout.get("indicators", {}).get("dist_visual", {}).get("source", "gpmf")
        if dist_src == "gpx":
            gpx_trk_l = gpx_track_samples or []
            if gpx_trk_l:
                max_distance_m = gpx_trk_l[-1][1]
        elif dist_src == "fit":
            fit_trk_l = (fit_data or {}).get("track", [])
            if fit_trk_l:
                max_distance_m = fit_trk_l[-1][1]
        if max_distance_m is None and track_samples:
            max_distance_m = track_samples[-1][1]

    # ── max_speed_kmh (per source) ────────────────────────────────────
    if _range_cache and "max_speed_kmh" in _range_cache:
        max_speed_kmh = _range_cache["max_speed_kmh"]
    else:
        max_speed_kmh = None
        spd_src = layout.get("indicators", {}).get("speed_visual", {}).get("source", "gpmf")
        if spd_src == "gpx":
            spd_for_range = (gpx_speed_samples or []) or speed_samples
        elif spd_src == "fit":
            spd_for_range = (fit_data or {}).get("speed", []) or speed_samples
        else:
            spd_for_range = speed_samples
        if spd_for_range:
            spd_vals = [s for _, s in spd_for_range]
            if spd_vals:
                max_speed_kmh = max(spd_vals)

    # ── min_alt / max_alt (per source) ────────────────────────────────
    if _range_cache and "min_alt" in _range_cache:
        min_alt = _range_cache["min_alt"]
        max_alt = _range_cache["max_alt"]
    else:
        min_alt = None
        max_alt = None
        alt_src = layout.get("indicators", {}).get("alt_visual", {}).get("source", "gpmf")
        if alt_src == "gpx":
            alt_for_range = (gpx_alt_samples or []) or alt_samples
        elif alt_src == "fit":
            alt_for_range = (fit_data or {}).get("alt", []) or alt_samples
        else:
            alt_for_range = alt_samples
        if alt_for_range:
            alts = [a for _, a in alt_for_range]
            if alts:
                min_alt = min(alts)
                max_alt = max(alts)
    profiler.record(
        "telemetry.range_calculations",
        (time.perf_counter() - section_started) * 1000.0,
    )

    # ── FIT / extra values ────────────────────────────────────────────
    section_started = time.perf_counter()

    resolved_this_frame: dict[str, Any] = {}

    def profiled_resolve(field_name: str):
        if field_name in resolved_this_frame:
            return resolved_this_frame[field_name]
        if not resolve_cache_value:
            resolved_this_frame[field_name] = 0.0
            return 0.0
        resolve_started = time.perf_counter()
        value = resolve_cache_value(field_name, target_dt)
        profiler.record(
            "telemetry.resolve_cache_value",
            (time.perf_counter() - resolve_started) * 1000.0,
        )
        resolved_this_frame[field_name] = value
        if resolve_stats is not None:
            resolve_stats["calls"] = int(resolve_stats.get("calls", 0)) + 1
            per_field = resolve_stats.setdefault("per_field", {})
            per_field[field_name] = int(per_field.get(field_name, 0)) + 1
        return value

    if fit_field_plan is None:
        # Compatibility path for preview and non-AMD exporters.  AMD production
        # always supplies a plan built once from its immutable export snapshot.
        standard_resolve_fields = set(_STANDARD_RESOLVE_CONSUMERS.values())
    else:
        standard_resolve_fields = set(
            fit_field_plan.get("active_standard_resolve_fields", [])
        )

    power_value = profiled_resolve("power") if "power" in standard_resolve_fields else None
    atemp_value = profiled_resolve("atemp") if "atemp" in standard_resolve_fields else None
    hr_value = profiled_resolve("hr") if "hr" in standard_resolve_fields else None
    cad_value = profiled_resolve("cad") if "cad" in standard_resolve_fields else None
    battery_value = profiled_resolve("battery") if "battery" in standard_resolve_fields else None

    # ── Elapsed time & average speed (for time_display) ───────────────
    elapsed_seconds = 0.0
    if start_dt_utc is not None and target_dt is not None:
        elapsed_seconds = max(0.0, (target_dt - start_dt_utc).total_seconds())

    avg_speed_kmh = 0.0
    if elapsed_seconds > 0 and distance_m > 0:
        # average speed = total distance / total time * 3.6 (m/s → km/h)
        avg_speed_kmh = (distance_m / elapsed_seconds) * 3.6

    # ── Build extra_indicators (FIT fields + remaining dynamic) ───────
    from src.indicators.registry import HARDCODED_KEYS

    # Sensible default units for known FIT field names (used when the layout
    # config does not provide an explicit unit).
    FIT_UNIT_HINTS: dict[str, str] = {
        "speed": "km/h", "enhanced_speed": "km/h", "ground_speed": "km/h",
        "distance": "km", "altitude": "m", "enhanced_altitude": "m",
        "heart_rate": "BPM", "cadence": "rpm", "power": "W",
        "temperature": "\u00b0C", "torque_effectiveness": "%",
        "vertical_oscillation": "mm", "stance_time": "ms",
    }

    extra_indicators: dict[str, tuple[float, str, str]] = {}

    # 1) FIT fields (from extra_field_keys list or from layout keys)
    if fit_field_plan is not None:
        fit_keys = [
            f"fit_{field_name}_text"
            for field_name in fit_field_plan.get("active_fit_fields", [])
        ]
    else:
        raw_fit_keys = extra_field_keys if extra_field_keys is not None else []
        fit_keys = []
        for k in raw_fit_keys:
            if k.startswith("fit_") and k.endswith("_text"):
                fit_keys.append(k)
            else:
                fit_keys.append(f"fit_{k}_text")

        for k in layout.get("indicators", {}):
            if k.startswith("fit_") and k.endswith("_text") and k not in fit_keys:
                fit_keys.append(k)

    for key in fit_keys:
        field_name = key[4:-5]
        val = profiled_resolve(field_name) or 0.0
        cfg = layout.get("indicators", {}).get(key, {})
        unit = cfg.get("unit") or FIT_UNIT_HINTS.get(field_name, "")
        label = cfg.get("label", field_name)
        extra_indicators[key] = (val, unit, label)

    profiler.record(
        "telemetry.dynamic_fit_fields",
        (time.perf_counter() - section_started) * 1000.0,
    )

    # 2) Remaining dynamic indicators (non-hardcoded, not already captured)
    for key in list(layout.get("indicators", {}).keys()):
        if key in HARDCODED_KEYS or key in extra_indicators:
            continue
        cfg = layout["indicators"][key]
        val = 0.0
        unit = cfg.get("unit", "")
        label = cfg.get("label", key)
        extra_indicators[key] = (val, unit, label)

    # ── Position / chart data ─────────────────────────────────────────
    section_started = time.perf_counter()
    current_position = (
        current_index / max(1, total_frames - 1)
        if total_frames > 1 else 0.0
    )
    profiler.record(
        "telemetry.graph_data",
        (time.perf_counter() - section_started) * 1000.0,
    )

    # ── GPS track ─────────────────────────────────────────────────────
    section_started = time.perf_counter()
    gps_trk: list = gps_track or []
    profiler.record(
        "telemetry.map_gps_data",
        (time.perf_counter() - section_started) * 1000.0,
    )

    return {
        "date_text": date_text,
        "time_text": time_text,
        "speed_value": speed_value,
        "distance_m": distance_m,
        "max_distance_m": max_distance_m,
        "alt_value": alt_value,
        "min_alt": min_alt,
        "max_alt": max_alt,
        "iso_value": iso_value,
        "exposure_value": exposure_value,
        "temp_value": temp_value,
        "indicator_values": indicator_values,
        "max_speed_kmh": max_speed_kmh,
        "power_value": power_value,
        "atemp_value": atemp_value,
        "hr_value": hr_value,
        "cad_value": cad_value,
        "battery_value": battery_value,
        "chart_data": chart_data or {},
        "current_position": current_position,
        "extra_indicators": extra_indicators,
        "gps_track": gps_trk,
        "target_dt": target_dt,
        "start_dt_utc": start_dt_utc,
        "elapsed_seconds": elapsed_seconds,
        "avg_speed_kmh": avg_speed_kmh,
    }
