"""ETAP 5N — precomputed telemetry frame cache.

``AMD_TELEMETRY_MODE=PRECOMPUTED`` precomputes, once per export, every per-frame
telemetry value that depends only on the frame timeline and the export
configuration (FIT/GPMF/GPX samples, layout dependency plan).  The render hot
path then becomes a cache lookup instead of re-running interpolation, the FIT
resolver, GPMF interpolation and per-frame dict construction.

The cache is built with the exact same interpolation / resolver functions used
by the reference path (``src.indicators.frame_data.prepare_overlay_frame_data``),
so values are value/type identical by construction; an explicit all-frames
value gate asserts zero mismatches.
"""
from __future__ import annotations

import sys
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Callable, Optional

from src.indicators.registry import HARDCODED_KEYS
from src.indicators.chart_builder import clip_chart_data


# Sensible default units for known FIT field names (identical to the reference
# path in src/indicators/frame_data.py).
FIT_UNIT_HINTS: dict[str, str] = {
    "speed": "km/h", "enhanced_speed": "km/h", "ground_speed": "km/h",
    "distance": "km", "altitude": "m", "enhanced_altitude": "m",
    "heart_rate": "BPM", "cadence": "rpm", "power": "W",
    "temperature": "\u00b0C", "torque_effectiveness": "%",
    "vertical_oscillation": "mm", "stance_time": "ms",
}


@dataclass(slots=True)
class _FrameRec:
    """Lightweight per-frame telemetry record (one per exported frame)."""
    date_text: str
    time_text: str
    speed_value: Optional[float]
    distance_m: Optional[float]
    alt_value: Optional[float]
    iso_value: float
    exposure_value: float
    temp_value: float
    indicator_values: dict[str, float]
    fit_vals: tuple
    dynamic_vals: tuple
    std_vals: tuple
    current_position: float
    elapsed_seconds: float
    avg_speed_kmh: float
    target_dt: datetime


@dataclass(slots=True)
class _Static:
    """Per-export (frame-independent) telemetry values."""
    max_distance_m: Optional[float]
    max_speed_kmh: Optional[float]
    min_alt: Optional[float]
    max_alt: Optional[float]
    chart_data: dict
    gps_track: list
    start_dt_utc: Optional[datetime]
    fit_keys: tuple
    fit_units: dict[str, str]
    fit_labels: dict[str, str]
    remaining_extra: dict[str, tuple]
    dynamic_keys: tuple
    dynamic_meta: dict[str, tuple]
    std_names: tuple


class TelemetryFrameCache:
    """frame_index -> precomputed telemetry dict (PRECOMPUTED hot path)."""

    __slots__ = ("records", "static", "build_ms", "memory_bytes", "frames",
                 "resolver_calls", "interpolation_calls", "gpmf_lookups")

    def __init__(self, records, static, build_ms, memory_bytes,
                 resolver_calls, interpolation_calls, gpmf_lookups):
        self.records = records
        self.static = static
        self.build_ms = build_ms
        self.memory_bytes = memory_bytes
        self.frames = len(records)
        self.resolver_calls = resolver_calls
        self.interpolation_calls = interpolation_calls
        self.gpmf_lookups = gpmf_lookups

    def lookup(self, frame_idx: int) -> dict[str, Any]:
        """Return the frame_kwargs dict for ``frame_idx`` (identical shape to
        ``prepare_overlay_frame_data``).  No interpolation / resolver work."""
        rec = self.records[frame_idx]
        st = self.static
        extra_indicators: dict[str, tuple] = {}
        fit_vals = rec.fit_vals
        for i, key in enumerate(st.fit_keys):
            extra_indicators[key] = (
                fit_vals[i], st.fit_units[key], st.fit_labels[key],
            )
        if st.remaining_extra:
            extra_indicators.update(st.remaining_extra)
        for i, key in enumerate(st.dynamic_keys):
            unit, label = st.dynamic_meta[key]
            extra_indicators[key] = (rec.dynamic_vals[i], unit, label)
        std = rec.std_vals
        return {
            "date_text": rec.date_text,
            "time_text": rec.time_text,
            "speed_value": rec.speed_value,
            "distance_m": rec.distance_m,
            "max_distance_m": st.max_distance_m,
            "alt_value": rec.alt_value,
            "min_alt": st.min_alt,
            "max_alt": st.max_alt,
            "iso_value": rec.iso_value,
            "exposure_value": rec.exposure_value,
            "temp_value": rec.temp_value,
            "indicator_values": rec.indicator_values,
            "max_speed_kmh": st.max_speed_kmh,
            "power_value": std[0],
            "atemp_value": std[1],
            "hr_value": std[2],
            "cad_value": std[3],
            "battery_value": std[4],
            "chart_data": st.chart_data or {},
            "current_position": rec.current_position,
            "extra_indicators": extra_indicators,
            "gps_track": st.gps_track,
            "target_dt": rec.target_dt,
            "start_dt_utc": st.start_dt_utc,
            "elapsed_seconds": rec.elapsed_seconds,
            "avg_speed_kmh": rec.avg_speed_kmh,
        }

    def stats(self) -> dict[str, Any]:
        return {
            "frames": self.frames,
            "build_ms": self.build_ms,
            "memory_bytes": self.memory_bytes,
            "memory_mib": self.memory_bytes / (1024.0 * 1024.0),
            "resolver_calls_per_frame": (
                self.resolver_calls / self.frames if self.frames else 0.0
            ),
            "interpolation_calls_per_frame": (
                self.interpolation_calls / self.frames if self.frames else 0.0
            ),
            "gpmf_lookups_per_frame": (
                self.gpmf_lookups / self.frames if self.frames else 0.0
            ),
            "structure": "list[slots-FrameRec] + shared static",
        }


def _target_dt(base_dt: datetime, frame_idx: int, target_fps: float) -> datetime:
    """Reproduce the reference loop's ``curr_dt`` exactly."""
    return base_dt + timedelta(seconds=frame_idx / target_fps)


def build_telemetry_cache(
    *,
    layout: dict[str, Any],
    base_dt: datetime,
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
    chart_data: Optional[dict[str, list[float]]] = None,
    resolve_cache_value: Optional[Callable] = None,
    _range_cache: Optional[dict] = None,
    fit_field_plan: Optional[dict[str, list[str]]] = None,
    total_frames: int = 1,
    target_fps: float = 29.97,
) -> TelemetryFrameCache:
    """Build the per-frame telemetry cache for an export.

    Every per-frame value is computed with the exact same interpolation /
    resolver functions used by the reference path, so results are identical.
    """
    from src.telemetry_extract import (
        interpolate_speed, interpolate_distance, interpolate_altitude,
        interpolate_iso, interpolate_exposure, interpolate_temperature,
    )

    iso_s = iso_samples or []
    exposure_s = exposure_samples or []
    temp_s = temperature_samples or []
    gpx_spd = gpx_speed_samples or []
    gpx_trk = gpx_track_samples or []
    gpx_alt = gpx_alt_samples or []
    fit = fit_data or {}
    fit_spd = fit.get("speed", [])
    fit_trk = fit.get("track", [])
    fit_alt = fit.get("alt", [])

    # ── static (per-export) values ──────────────────────────────────────
    rc = _range_cache or {}
    max_distance_m = rc.get("max_distance_m")
    max_speed_kmh = rc.get("max_speed_kmh")
    min_alt = rc.get("min_alt")
    max_alt = rc.get("max_alt")

    indicators = layout.get("indicators", {})

    # active FIT fields -> keys, units, labels
    if fit_field_plan is not None:
        active_fit = fit_field_plan.get("active_fit_fields", [])
        std_names = tuple(fit_field_plan.get("active_standard_resolve_fields", []))
    else:
        active_fit = []
        std_names = tuple()
        for k, cfg in indicators.items():
            if k.startswith("fit_") and k.endswith("_text") and cfg.get("enabled", True):
                field_name = k[4:-5]
                if field_name and field_name in fit and field_name not in active_fit:
                    active_fit.append(field_name)
        # legacy standard consumers (mirrors frame_data default)
        std_consumers = ("power", "atemp", "hr", "cad", "battery")
        std_names = tuple(
            f for f in std_consumers if f"fit_{f}_text" in indicators
        ) if False else std_names

    fit_keys = tuple(f"fit_{name}_text" for name in active_fit)
    fit_units: dict[str, str] = {}
    fit_labels: dict[str, str] = {}
    for name, key in zip(active_fit, fit_keys):
        cfg = indicators.get(key, {})
        fit_units[key] = cfg.get("unit") or FIT_UNIT_HINTS.get(name, "")
        fit_labels[key] = cfg.get("label", name)

    imu_fields = {
        "accel_x_text": ("accel_x", "m/s", "Accelerometer X"),
        "accel_y_text": ("accel_y", "m/s", "Accelerometer Y"),
        "accel_z_text": ("accel_z", "m/s", "Accelerometer Z"),
        "accel_magnitude_text": ("accel_magnitude", "m/s", "Accelerometer Magnitude"),
        "gyro_x_text": ("gyro_x", "rad/s", "Gyroscope X"),
        "gyro_y_text": ("gyro_y", "rad/s", "Gyroscope Y"),
        "gyro_z_text": ("gyro_z", "rad/s", "Gyroscope Z"),
        "gyro_magnitude_text": ("gyro_magnitude", "rad/s", "Gyroscope Magnitude"),
    }
    dynamic_keys = tuple(
        key for key, cfg in indicators.items()
        if key in imu_fields and isinstance(cfg, dict) and cfg.get("enabled", True)
    )
    dynamic_meta = {
        key: (indicators[key].get("unit") or imu_fields[key][1],
              indicators[key].get("label") or imu_fields[key][2])
        for key in dynamic_keys
    }

    # Keep configured dynamic indicators in the runtime layout, but preserve
    # unavailable values as None. The compositor hides those entries.
    remaining_extra: dict[str, tuple] = {}
    for key, cfg in indicators.items():
        if key in HARDCODED_KEYS or key in fit_keys or key in dynamic_keys:
            continue
        if not isinstance(cfg, dict):
            continue
        if key.startswith("fit_") and key.endswith("_text"):
            remaining_extra[key] = (
                None, cfg.get("unit", ""), cfg.get("label", key),
            )
            continue
        remaining_extra[key] = (
            None, cfg.get("unit", ""), cfg.get("label", key),
        )

    gps_trk: list = gps_track or []

    # ── per-frame build loop (single-threaded, small dataset) ───────────
    build_started = time.perf_counter()
    records: list[_FrameRec] = []
    resolver_calls = 0
    interpolation_calls = 0
    gpmf_lookups = 0

    for frame_idx in range(total_frames):
        target_dt = _target_dt(base_dt, frame_idx, target_fps)
        local_dt = target_dt + timedelta(hours=tz_offset_hours)
        date_text = local_dt.strftime("%Y-%m-%d")
        time_text = local_dt.strftime("%H:%M:%S")

        # per-source indicator values (speed/dist/alt)
        indicator_values: dict[str, float] = {}
        for ind_key in ("speed_visual", "speed_text", "dist_visual", "dist_text",
                        "alt_visual", "alt_text"):
            if ind_key not in indicators:
                continue
            ind_cfg = indicators.get(ind_key, {})
            if not ind_cfg.get("enabled", True):
                continue
            src = ind_cfg.get("source", "gpmf")
            if src == "gpx":
                spd_s, trk_s, alt_s = gpx_spd, gpx_trk, gpx_alt
            elif src == "fit":
                spd_s, trk_s, alt_s = fit_spd, fit_trk, fit_alt
            else:
                spd_s, trk_s, alt_s = speed_samples, track_samples, alt_samples
            if ind_key in ("speed_visual", "speed_text"):
                indicator_values[ind_key] = interpolate_speed(spd_s, target_dt) if spd_s else None
                interpolation_calls += 1
            elif ind_key in ("dist_visual", "dist_text"):
                indicator_values[ind_key] = interpolate_distance(trk_s, target_dt) if trk_s else None
                interpolation_calls += 1
            elif ind_key in ("alt_visual", "alt_text"):
                indicator_values[ind_key] = interpolate_altitude(alt_s, target_dt) if alt_s else None
                interpolation_calls += 1

        speed_value = indicator_values.get(
            "speed_visual",
            indicator_values.get("speed_text", interpolate_speed(speed_samples, target_dt) if speed_samples else None),
        )
        distance_m = indicator_values.get(
            "dist_visual",
            indicator_values.get("dist_text", interpolate_distance(track_samples, target_dt) if track_samples else None),
        )
        alt_value = indicator_values.get(
            "alt_visual",
            indicator_values.get("alt_text", interpolate_altitude(alt_samples, target_dt) if alt_samples else None),
        )
        if "speed_visual" not in indicator_values:
            interpolation_calls += 1
        if "dist_visual" not in indicator_values:
            interpolation_calls += 1
        if "alt_visual" not in indicator_values:
            interpolation_calls += 1

        def _resolve_aux(field: str, key: str, fallback: Callable):
            cfg = layout.get("indicators", {}).get(key, {})
            source = cfg.get("source", "gpmf")
            if resolve_cache_value is not None:
                value = resolve_cache_value(field, source, target_dt, key)
                if value is not None:
                    return value
            return fallback(
                {"iso": iso_s, "exposure": exposure_s, "temperature": temp_s}[field],
                target_dt,
            ) if source == "gpmf" and {"iso": iso_s, "exposure": exposure_s, "temperature": temp_s}[field] else None

        iso_value = _resolve_aux("iso", "iso_text", interpolate_iso)
        exposure_value = _resolve_aux("exposure", "exposure_text", interpolate_exposure)
        temp_value = _resolve_aux("temperature", "temp_text", interpolate_temperature)
        interpolation_calls += 3
        gpmf_lookups += 3

        # standard resolve fields (power/atemp/hr/cad/battery)
        std_vals: list = []
        std_keys = {
            "power": "power_text", "atemp": "atemp_text", "hr": "hr_text",
            "cad": "cad_text", "battery": "battery_text",
        }
        for f in ("power", "atemp", "hr", "cad", "battery"):
            if f in std_names and resolve_cache_value is not None:
                cfg = layout.get("indicators", {}).get(std_keys[f], {})
                source = cfg.get("source", "gpx")
                std_vals.append(resolve_cache_value(f, source, target_dt, std_keys[f]))
                resolver_calls += 1
            else:
                std_vals.append(None)

        # FIT fields (deduplicated via the dependency plan sets)
        fit_vals: list = []
        for name in active_fit:
            if resolve_cache_value is None:
                v = None
            else:
                v = resolve_cache_value(name, "fit", target_dt, f"fit_{name}_text")
                resolver_calls += 1
            fit_vals.append(v)

        dynamic_vals: list = []
        for key in dynamic_keys:
            field_name = imu_fields[key][0]
            cfg = indicators.get(key, {})
            value = None
            if resolve_cache_value is not None:
                value = resolve_cache_value(
                    field_name, cfg.get("source", "gpmf"), target_dt, key,
                )
                resolver_calls += 1
            dynamic_vals.append(value)

        elapsed_seconds = 0.0
        if start_dt_utc is not None and target_dt is not None:
            elapsed_seconds = max(0.0, (target_dt - start_dt_utc).total_seconds())
        avg_speed_kmh = 0.0
        if elapsed_seconds > 0 and distance_m is not None and distance_m > 0:
            avg_speed_kmh = (distance_m / elapsed_seconds) * 3.6

        current_position = (
            frame_idx / max(1, total_frames - 1)
            if total_frames > 1 else 0.0
        )

        records.append(_FrameRec(
            date_text=date_text, time_text=time_text,
            speed_value=speed_value, distance_m=distance_m, alt_value=alt_value,
            iso_value=iso_value, exposure_value=exposure_value,
            temp_value=temp_value, indicator_values=indicator_values,
            fit_vals=tuple(fit_vals), dynamic_vals=tuple(dynamic_vals),
            std_vals=tuple(std_vals),
            current_position=current_position, elapsed_seconds=elapsed_seconds,
            avg_speed_kmh=avg_speed_kmh, target_dt=target_dt,
        ))

    build_ms = (time.perf_counter() - build_started) * 1000.0
    memory_bytes = (
        sys.getsizeof(records)
        + sum(sys.getsizeof(r) for r in records)
        + sys.getsizeof(_Static) + 512
    )
    static = _Static(
        max_distance_m=max_distance_m, max_speed_kmh=max_speed_kmh,
        min_alt=min_alt, max_alt=max_alt, chart_data=chart_data or {},
        gps_track=gps_trk, start_dt_utc=start_dt_utc, fit_keys=fit_keys,
        fit_units=fit_units, fit_labels=fit_labels,
        remaining_extra=remaining_extra, dynamic_keys=dynamic_keys,
        dynamic_meta=dynamic_meta, std_names=std_names,
    )
    return TelemetryFrameCache(
        records, static, build_ms, memory_bytes,
        resolver_calls, interpolation_calls, gpmf_lookups,
    )
