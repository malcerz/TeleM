"""Worker cache management for FFmpeg overlay rendering.

Stores telemetry data and helper functions inside a global cache dictionary (WORKER_CACHE)
to avoid IPC overhead in child processes.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Optional

from src.overlay_renderer import build_chart_data
from src.telemetry_extract import (
    interpolate_speed,
    interpolate_distance,
    interpolate_altitude,
    interpolate_value,
)
from src.telemetry_heading import interpolate_heading
from src.telemetry_slope import interpolate_slope

WORKER_CACHE: dict[str, Any] = {}


def init_worker(
    video_width: int,
    video_height: int,
    font_path: str,
    layout: dict[str, Any],
    field_samples: dict[str, Any],
    max_distance_m: float | None = None,
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
    start_dt_utc: Optional[datetime] = None,
    tz_offset_hours: Optional[float] = None,
    speed_samples: Optional[list] = None,
    track_samples: Optional[list] = None,
    alt_samples: Optional[list] = None,
    target_fps: Optional[float] = None,
    update_rate_step: int = 1,
    total_overlay_frames: Optional[int] = None,
    cut_regions: Optional[list[tuple[float, float]]] = None,
    effective_rotation: int = 0,
    hud_bbox: Optional[tuple[int, int, int, int]] = None,
    hud_regions: Optional[list[tuple[int, int, int, int, int, int]]] = None,
    hud_rotate_180: bool = False,
    telemetry_cache: Optional[Any] = None,
    video_timeline: Optional[Any] = None,
) -> None:
    """Initialise WORKER_CACHE with all telemetry data for worker processes.

    ``video_timeline`` (ETAP 4B) is the shared multi-file time axis; workers use
    it to map ``global_time -> absolute target_dt``.  It is pickle-friendly
    (plain dataclasses + datetimes) so it can be passed to process-pool workers.
    """
    WORKER_CACHE["video_width"] = video_width
    WORKER_CACHE["video_height"] = video_height
    WORKER_CACHE["font_path"] = font_path
    WORKER_CACHE["layout"] = layout
    WORKER_CACHE["_telemetry_cache"] = telemetry_cache
    WORKER_CACHE["video_timeline"] = video_timeline
    field_samples = field_samples or {}
    WORKER_CACHE["field_samples"] = field_samples
    WORKER_CACHE["max_distance_m"] = max_distance_m or 1000.0
    WORKER_CACHE["iso_samples"] = iso_samples or []
    WORKER_CACHE["exposure_samples"] = exposure_samples or []
    WORKER_CACHE["temperature_samples"] = temperature_samples or []
    WORKER_CACHE["gpx_speed_samples"] = gpx_speed_samples or []
    WORKER_CACHE["gpx_track_samples"] = gpx_track_samples or []
    WORKER_CACHE["gpx_alt_samples"] = gpx_alt_samples or []
    WORKER_CACHE["gpx_power_samples"] = gpx_power_samples or []
    WORKER_CACHE["gpx_atemp_samples"] = gpx_atemp_samples or []
    WORKER_CACHE["gpx_hr_samples"] = gpx_hr_samples or []
    WORKER_CACHE["gpx_cad_samples"] = gpx_cad_samples or []
    WORKER_CACHE["gpx_heading_samples"] = field_samples.get("gpx_heading_samples", []) or []
    WORKER_CACHE["gpx_slope_samples"] = field_samples.get("gpx_slope_samples", []) or []
    WORKER_CACHE["fit_data"] = fit_data or {}
    WORKER_CACHE["gps_track"] = gps_track or []
    WORKER_CACHE["start_dt_utc"] = start_dt_utc
    WORKER_CACHE["tz_offset_hours"] = tz_offset_hours
    WORKER_CACHE["speed_samples"] = speed_samples or []
    WORKER_CACHE["track_samples"] = track_samples or []
    WORKER_CACHE["alt_samples"] = alt_samples or []
    WORKER_CACHE["target_fps"] = target_fps
    WORKER_CACHE["update_rate_step"] = update_rate_step
    WORKER_CACHE["total_overlay_frames"] = total_overlay_frames or 1
    WORKER_CACHE["_cut_regions"] = cut_regions or []
    WORKER_CACHE["effective_rotation"] = effective_rotation
    WORKER_CACHE["hud_bbox"] = hud_bbox
    WORKER_CACHE["hud_regions"] = hud_regions
    WORKER_CACHE["hud_rotate_180"] = hud_rotate_180
    if "_font_cache" not in WORKER_CACHE:
        WORKER_CACHE["_font_cache"] = {}

    # Precompute chart data for workers (identical for every frame)
    duration_s = (total_overlay_frames / target_fps) if (total_overlay_frames and target_fps) else None
    # ETAP 4B: with a multi-file timeline use the REAL absolute end (max clip
    # absolute_end) instead of start_dt_utc + project_duration (wrong with gaps).
    end_dt_utc = None
    if video_timeline is not None and getattr(video_timeline, "clip_count", 0):
        try:
            from src.multifile import timeline_absolute_end
            end_dt_utc = timeline_absolute_end(video_timeline)
        except Exception:
            end_dt_utc = None
    if end_dt_utc is None and start_dt_utc and duration_s:
        end_dt_utc = start_dt_utc + timedelta(seconds=duration_s)
    source_ranges = {}
    if fit_data:
        all_fit_pts = [s for s in fit_data.values() if s]
        if all_fit_pts:
            source_ranges["fit"] = (
                min(s[0][0] for s in all_fit_pts),
                max(s[-1][0] for s in all_fit_pts),
            )
    WORKER_CACHE["_precomputed_chart_data"] = build_chart_data(
        layout, _get_source_samples, _resolve_cache_samples,
        start_dt_utc=start_dt_utc, end_dt_utc=end_dt_utc,
        source_activity_ranges=source_ranges,
    )

    # ── Precompute static ranges (max_distance_m, max_speed_kmh, min/max_alt) ──
    _prep_cache: dict[str, Any] = {}
    indic = layout.get("indicators", {})

    # max_distance_m
    trk = track_samples or []
    gpx_trk = gpx_track_samples or []
    fit_trk = fit_data.get("track", []) if fit_data else []
    dist_src = indic.get("dist_visual", {}).get("source", "gpmf")
    if dist_src == "gpx":
        trk_for_range = gpx_trk
    elif dist_src == "fit":
        trk_for_range = fit_trk
    else:
        trk_for_range = trk
    _prep_cache["max_distance_m"] = trk_for_range[-1][1] if trk_for_range else None

    # max_speed_kmh
    spd = speed_samples or []
    gpx_spd = gpx_speed_samples or []
    fit_spd = fit_data.get("speed", []) if fit_data else []
    spd_src = indic.get("speed_visual", {}).get("source", "gpmf")
    if spd_src == "gpx":
        spd_for_range = gpx_spd
    elif spd_src == "fit":
        spd_for_range = fit_spd
    else:
        spd_for_range = spd
    if spd_for_range:
        spd_vals = [s for _, s in spd_for_range]
        _prep_cache["max_speed_kmh"] = max(spd_vals) if spd_vals else None
    else:
        _prep_cache["max_speed_kmh"] = None

    # min_alt / max_alt
    alt_s = alt_samples or []
    gpx_alt_s = gpx_alt_samples or []
    fit_alt_s = fit_data.get("alt", []) if fit_data else []
    alt_src = indic.get("alt_visual", {}).get("source", "gpmf")
    if alt_src == "gpx":
        alt_for_range = gpx_alt_s
    elif alt_src == "fit":
        alt_for_range = fit_alt_s
    else:
        alt_for_range = alt_s
    if alt_for_range:
        alts = [a for _, a in alt_for_range]
        _prep_cache["min_alt"] = min(alts) if alts else None
        _prep_cache["max_alt"] = max(alts) if alts else None
    else:
        _prep_cache["min_alt"] = None
        _prep_cache["max_alt"] = None

    WORKER_CACHE["_prep_cache"] = _prep_cache

    # ── Cut regions & rotation ─────────────────────────────────────────────
    WORKER_CACHE["_cut_regions"] = cut_regions or []
    WORKER_CACHE["effective_rotation"] = effective_rotation


def _get_source_samples(source_type: str) -> tuple[list, list, list]:
    """Return (speed, track, alt) samples for exactly the given source."""
    gpx_spd = WORKER_CACHE.get("gpx_speed_samples", [])
    gpx_trk = WORKER_CACHE.get("gpx_track_samples", [])
    gpx_alt = WORKER_CACHE.get("gpx_alt_samples", [])
    fit_spd = WORKER_CACHE.get("fit_data", {}).get("speed", [])
    fit_trk = WORKER_CACHE.get("fit_data", {}).get("track", [])
    fit_alt = WORKER_CACHE.get("fit_data", {}).get("alt", [])
    gpmf_spd = WORKER_CACHE.get("field_samples", {}).get("speed_samples", [])
    gpmf_trk = WORKER_CACHE.get("field_samples", {}).get("track_samples", [])
    gpmf_alt = WORKER_CACHE.get("field_samples", {}).get("alt_samples", [])
    if source_type == "gpx":
        return (gpx_spd, gpx_trk, gpx_alt)
    if source_type == "fit":
        return (fit_spd, fit_trk, fit_alt)
    return (gpmf_spd, gpmf_trk, gpmf_alt)


def _worker_lean_roll(axis: str) -> list:
    """Precomputed roll timeline for the final-render worker (ETAP 13).

    Mirrors ``TelemetryDataManager._get_lean_roll_samples`` so the AMD/NVIDIA/
    Intel/CPU final path produces the same deterministic roll as preview.
    """
    axis = str(axis).strip().lower()
    if axis not in ("x", "y", "z"):
        axis = "z"
    cache: dict = WORKER_CACHE.setdefault("_lean_roll", {})
    if axis in cache:
        return cache[axis]
    from src.telemetry_imu import compute_roll_timeline, merge_axis_samples
    fs = WORKER_CACHE.get("field_samples", {}) or {}
    accel = merge_axis_samples(
        fs.get("accel_x_samples", []), fs.get("accel_y_samples", []),
        fs.get("accel_z_samples", []),
    )
    gyro = merge_axis_samples(
        fs.get("gyro_x_samples", []), fs.get("gyro_y_samples", []),
        fs.get("gyro_z_samples", []),
    )
    timeline = compute_roll_timeline(accel=accel, gyro=gyro, roll_axis=axis)
    cache[axis] = timeline
    return timeline


def _resolve_cache_value(
    field_name: str, source: str, target_dt: datetime,
    indicator_key: str | None = None,
) -> Any:
    """Resolve one field from one explicit source using the shared contract."""
    del indicator_key
    if str(field_name).startswith("lean_roll_"):
        from src.telemetry_imu import interpolate_roll
        axis = str(field_name).split("_")[-1]
        return interpolate_roll(_worker_lean_roll(axis), target_dt)
    samples = _resolve_cache_samples(field_name, source)
    if not samples:
        return None
    if field_name == "heading":
        return interpolate_heading(samples, target_dt)
    if field_name == "slope":
        return interpolate_slope(samples, target_dt)
    # Linear interpolation for speed/distance/altitude fields (smooth per frame),
    # step for the rest — must match telemetry_manager.resolve_value.
    if field_name in ("speed", "enhanced_speed"):
        return interpolate_speed(samples, target_dt)
    if field_name in ("distance", "dist", "track"):
        return interpolate_distance(samples, target_dt)
    if field_name in ("alt", "enhanced_altitude", "altitude"):
        return interpolate_altitude(samples, target_dt)
    return interpolate_value(samples, target_dt)


def _resolve_cache_samples(
    field_name: str, source: str = "fit", indicator_key: str | None = None
) -> list:
    """Return raw samples from exactly ``source``; no cross-source fallback."""
    del indicator_key
    field_samples = WORKER_CACHE.get("field_samples", {}) or {}
    gpmf_map = {
        "speed": "speed_samples", "alt": "alt_samples", "altitude": "alt_samples",
        "dist": "track_samples", "track": "track_samples", "iso": "iso_samples",
        "exposure": "exposure_samples", "temperature": "temperature_samples",
        "heading": "heading_samples",
        "slope": "slope_samples",
        "accel_x": "accel_x_samples", "accel_y": "accel_y_samples",
        "accel_z": "accel_z_samples", "accel_magnitude": "accel_magnitude_samples",
        "gyro_x": "gyro_x_samples", "gyro_y": "gyro_y_samples",
        "gyro_z": "gyro_z_samples", "gyro_magnitude": "gyro_magnitude_samples",
    }
    gpx_map = {
        "speed": "gpx_speed_samples", "alt": "gpx_alt_samples", "altitude": "gpx_alt_samples",
        "dist": "gpx_track_samples", "track": "gpx_track_samples", "power": "gpx_power_samples",
        "atemp": "gpx_atemp_samples", "hr": "gpx_hr_samples", "cad": "gpx_cad_samples",
        "battery": "gpx_battery_samples",
        "heading": "gpx_heading_samples",
        "slope": "gpx_slope_samples",
    }
    if source == "gpmf":
        key = gpmf_map.get(field_name, "")
        if key and key in field_samples and field_samples[key]:
            return list(field_samples[key])
        if key and key in WORKER_CACHE and WORKER_CACHE[key]:
            return list(WORKER_CACHE[key])
        return list(field_samples.get(key, []) or [])
    if source == "gpx":
        return list(WORKER_CACHE.get(gpx_map.get(field_name, ""), []) or [])
    if source == "fit":
        fit_data = WORKER_CACHE.get("fit_data", {})
        aliases = {
            "power": ("power", "curVpower"), "hr": ("hr", "heart_rate"),
            "cad": ("cad", "cadence"), "atemp": ("atemp", "temperature"),
            "battery": ("battery", "battery_soc"),
        }.get(field_name, (field_name,))
        for name in aliases:
            if fit_data.get(name):
                return list(fit_data[name])
        return []
    return []
