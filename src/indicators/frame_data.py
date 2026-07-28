"""Shared overlay frame data preparation.

Extracted from ``overlay_renderer.py``.

Consolidates the data-preparation logic that was previously duplicated
between ``_render_preview`` (controller.py) and ``render_overlay_frame``
(ffmpeg_pipeline.py).  Both callers invoke this single function.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Callable, Optional


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
) -> dict[str, Any]:
    """Prepare all values needed by ``compose_overlay`` for a single frame.

    This function consolidates the data-preparation logic that was previously
    duplicated between ``_render_preview`` (controller.py) and
    ``render_overlay_frame`` (ffmpeg_pipeline.py).  Both callers now invoke
    this single function, eliminating any future drift.

    Returns a dict suitable for ``**kwargs`` to ``compose_overlay``.
    """
    from src.telemetry_extract import (
        interpolate_speed, interpolate_distance, interpolate_altitude,
        interpolate_iso, interpolate_exposure, interpolate_temperature,
    )

    # ── Time strings ──────────────────────────────────────────────────
    local_dt = target_dt + timedelta(hours=tz_offset_hours)
    date_text = local_dt.strftime("%Y-%m-%d")
    time_text = local_dt.strftime("%H:%M:%S")

    # ── Per-source indicator values (speed / dist / alt) ──────────────
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

    # ── max_distance_m (per source) ───────────────────────────────────
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

    # ── FIT / extra values ────────────────────────────────────────────
    power_value = resolve_cache_value("power", target_dt) if resolve_cache_value else 0.0
    atemp_value = resolve_cache_value("atemp", target_dt) if resolve_cache_value else 0.0
    hr_value = resolve_cache_value("hr", target_dt) if resolve_cache_value else 0.0
    cad_value = resolve_cache_value("cad", target_dt) if resolve_cache_value else 0.0
    battery_value = resolve_cache_value("battery", target_dt) if resolve_cache_value else 0.0

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

    extra_indicators: dict[str, tuple[float, str, str]] = {}

    # 1) FIT fields (from extra_field_keys list or from layout keys)
    fit_keys = extra_field_keys if extra_field_keys is not None else [
        k for k in layout.get("indicators", {})
        if k.startswith("fit_") and k.endswith("_text")
    ]
    for key in fit_keys:
        field_name = key[4:-5]
        if resolve_cache_value:
            val = resolve_cache_value(field_name, target_dt) or 0.0
        else:
            val = 0.0
        cfg = layout.get("indicators", {}).get(key, {})
        unit = cfg.get("unit", "")
        label = cfg.get("label", field_name)
        extra_indicators[key] = (val, unit, label)

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
    current_position = (
        current_index / max(1, total_frames - 1)
        if total_frames > 1 else 0.0
    )

    # ── GPS track ─────────────────────────────────────────────────────
    gps_trk: list = gps_track or []

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
