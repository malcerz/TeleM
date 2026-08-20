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


import numpy as np
from src.ffmpeg.worker_cache import _resolve_cache_samples


def _vectorize_step(
    samples: list[tuple[datetime, Any]],
    target_dts: list[datetime],
    target_ts_arr: np.ndarray,
    ref_dt: datetime,
) -> list[Any]:
    """Vectorized STEP lookup with exact bisect_right - 1 semantics."""
    if not samples:
        return [None] * len(target_dts)
    
    sample_dts = [s[0].replace(tzinfo=None) if s[0].tzinfo is not None else s[0] for s in samples]
    sample_vals = [s[1] for s in samples]
    sample_ts = np.array([(dt - ref_dt).total_seconds() for dt in sample_dts], dtype=np.float64)
    
    idx = np.searchsorted(sample_ts, target_ts_arr, side="right") - 1
    
    out = [None] * len(target_dts)
    for k in range(len(target_dts)):
        i = idx[k]
        if i >= 0:
            out[k] = sample_vals[i]
    return out


def _vectorize_linear_speed(
    samples: list[tuple[datetime, float]],
    target_dts: list[datetime],
    target_ts_arr: np.ndarray,
    ref_dt: datetime,
) -> list[Optional[float]]:
    """Vectorized linear speed interpolation matching interpolate_speed exactly."""
    if not samples:
        return [None] * len(target_dts)
    sample_dts = [s[0].replace(tzinfo=None) if s[0].tzinfo is not None else s[0] for s in samples]
    sample_vals = np.array([s[1] for s in samples], dtype=np.float64)
    sample_ts = np.array([(dt - ref_dt).total_seconds() for dt in sample_dts], dtype=np.float64)
    
    interp_vals = np.interp(
        target_ts_arr, sample_ts, sample_vals,
        left=0.0, right=max(0.0, float(sample_vals[-1]))
    )
    interp_vals = np.maximum(0.0, interp_vals)
    return [float(v) for v in interp_vals]


def _vectorize_linear_distance(
    samples: list[tuple[datetime, float]],
    target_dts: list[datetime],
    target_ts_arr: np.ndarray,
    ref_dt: datetime,
) -> list[Optional[float]]:
    """Vectorized linear distance interpolation matching interpolate_distance exactly."""
    if not samples:
        return [None] * len(target_dts)
    sample_dts = [s[0].replace(tzinfo=None) if s[0].tzinfo is not None else s[0] for s in samples]
    sample_vals = np.array([s[1] for s in samples], dtype=np.float64)
    sample_ts = np.array([(dt - ref_dt).total_seconds() for dt in sample_dts], dtype=np.float64)
    
    interp_vals = np.interp(
        target_ts_arr, sample_ts, sample_vals,
        left=0.0, right=float(sample_vals[-1])
    )
    return [float(v) for v in interp_vals]


def _vectorize_linear_altitude(
    samples: list[tuple[datetime, float]],
    target_dts: list[datetime],
    target_ts_arr: np.ndarray,
    ref_dt: datetime,
) -> list[Optional[float]]:
    """Vectorized linear altitude interpolation matching interpolate_altitude exactly."""
    if not samples:
        return [None] * len(target_dts)
    sample_dts = [s[0].replace(tzinfo=None) if s[0].tzinfo is not None else s[0] for s in samples]
    sample_vals = np.array([s[1] for s in samples], dtype=np.float64)
    sample_ts = np.array([(dt - ref_dt).total_seconds() for dt in sample_dts], dtype=np.float64)
    
    interp_vals = np.interp(
        target_ts_arr, sample_ts, sample_vals,
        left=float(sample_vals[0]), right=float(sample_vals[-1])
    )
    return [float(v) for v in interp_vals]


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
    subtimer_dict: Optional[dict] = None,
) -> TelemetryFrameCache:
    """Build the per-frame telemetry cache for an export (ETAP 8P-B Fast Builder).

    Vectorized precomputation over the export timeline while strictly preserving
    the exact same interpolation / resolver contracts.
    """
    t_start = time.perf_counter()

    # 1. Timeline & Target datetimes
    t0_timeline = time.perf_counter()
    target_dts = [base_dt + timedelta(seconds=i / target_fps) for i in range(total_frames)]
    local_dts = [dt + timedelta(hours=tz_offset_hours) for dt in target_dts]
    date_texts = [dt.strftime("%Y-%m-%d") for dt in local_dts]
    time_texts = [dt.strftime("%H:%M:%S") for dt in local_dts]

    ref_dt = base_dt.replace(tzinfo=None) if base_dt.tzinfo is not None else base_dt
    target_dts_naive = [dt.replace(tzinfo=None) if dt.tzinfo is not None else dt for dt in target_dts]
    target_ts_arr = np.array([(dt - ref_dt).total_seconds() for dt in target_dts_naive], dtype=np.float64)
    t_timeline_ms = (time.perf_counter() - t0_timeline) * 1000.0

    # 2. Metadata & Static configuration
    t0_static = time.perf_counter()
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
        fit = fit_data or {}
        for k, cfg in indicators.items():
            if k.startswith("fit_") and k.endswith("_text"):
                field_name = k[4:-5]
                if field_name not in active_fit:
                    active_fit.append(field_name)

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

    remaining_extra: dict[str, tuple] = {}
    for key, cfg in indicators.items():
        if key in HARDCODED_KEYS or key in fit_keys or key in dynamic_keys:
            continue
        if not isinstance(cfg, dict):
            continue
        remaining_extra[key] = (None, cfg.get("unit", ""), cfg.get("label", key))

    gps_trk: list = gps_track or []
    t_static_ms = (time.perf_counter() - t0_static) * 1000.0

    # 3. Vectorized Linear Fields (Speed, Distance, Altitude)
    t0_linear = time.perf_counter()
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

    source_cache: dict[str, list] = {}
    def get_source_linear(src: str, field_type: str):
        cache_key = f"{src}_{field_type}"
        if cache_key in source_cache:
            return source_cache[cache_key]
        if src == "gpx":
            s_spd, s_trk, s_alt = gpx_spd, gpx_trk, gpx_alt
        elif src == "fit":
            s_spd, s_trk, s_alt = fit_spd, fit_trk, fit_alt
        else:
            s_spd, s_trk, s_alt = speed_samples, track_samples, alt_samples

        if field_type == "speed":
            arr = _vectorize_linear_speed(s_spd, target_dts, target_ts_arr, ref_dt)
        elif field_type == "dist":
            arr = _vectorize_linear_distance(s_trk, target_dts, target_ts_arr, ref_dt)
        else:
            arr = _vectorize_linear_altitude(s_alt, target_dts, target_ts_arr, ref_dt)
        source_cache[cache_key] = arr
        return arr

    ind_arrs: dict[str, list] = {}
    for ind_key in ("speed_visual", "speed_text", "dist_visual", "dist_text", "alt_visual", "alt_text"):
        if ind_key not in indicators:
            continue
        ind_cfg = indicators.get(ind_key, {})
        if not ind_cfg.get("enabled", True):
            continue
        src = ind_cfg.get("source", "gpmf")
        ftype = "speed" if "speed" in ind_key else ("dist" if "dist" in ind_key else "alt")
        ind_arrs[ind_key] = get_source_linear(src, ftype)

    speed_arr = ind_arrs.get(
        "speed_visual",
        ind_arrs.get("speed_text", get_source_linear("gpmf", "speed"))
    )
    dist_arr = ind_arrs.get(
        "dist_visual",
        ind_arrs.get("dist_text", get_source_linear("gpmf", "dist"))
    )
    alt_arr = ind_arrs.get(
        "alt_visual",
        ind_arrs.get("alt_text", get_source_linear("gpmf", "alt"))
    )
    t_linear_ms = (time.perf_counter() - t0_linear) * 1000.0

    # 4. GPMF Auxiliary Fields (ISO, Exposure, Temperature)
    t0_gpmf = time.perf_counter()
    def resolve_field_vectorized(field: str, key: str, fallback_samples: list):
        cfg = indicators.get(key, {})
        src = cfg.get("source", "gpmf")
        samples = _resolve_cache_samples(field, src) if resolve_cache_value is not None else None
        if not samples:
            samples = fallback_samples if src == "gpmf" else []
        return _vectorize_step(samples, target_dts, target_ts_arr, ref_dt)

    iso_arr = resolve_field_vectorized("iso", "iso_text", iso_s)
    exposure_arr = resolve_field_vectorized("exposure", "exposure_text", exposure_s)
    temp_arr = resolve_field_vectorized("temperature", "temp_text", temp_s)
    t_gpmf_ms = (time.perf_counter() - t0_gpmf) * 1000.0

    # 5. Standard Resolve Fields (Power, atemp, hr, cad, battery)
    t0_std = time.perf_counter()
    std_keys_map = {
        "power": "power_text", "atemp": "atemp_text", "hr": "hr_text",
        "cad": "cad_text", "battery": "battery_text",
    }
    std_field_arrs: list[list] = []
    for f in ("power", "atemp", "hr", "cad", "battery"):
        if f in std_names:
            cfg = indicators.get(std_keys_map[f], {})
            src = cfg.get("source", "gpx")
            samples = _resolve_cache_samples(f, src)
            if samples:
                if f in ("speed", "enhanced_speed"):
                    std_field_arrs.append(_vectorize_linear_speed(samples, target_dts, target_ts_arr, ref_dt))
                elif f in ("distance", "dist", "track"):
                    std_field_arrs.append(_vectorize_linear_distance(samples, target_dts, target_ts_arr, ref_dt))
                elif f in ("alt", "enhanced_altitude", "altitude"):
                    std_field_arrs.append(_vectorize_linear_altitude(samples, target_dts, target_ts_arr, ref_dt))
                else:
                    std_field_arrs.append(_vectorize_step(samples, target_dts, target_ts_arr, ref_dt))
            elif resolve_cache_value is not None:
                std_field_arrs.append([resolve_cache_value(f, src, dt, std_keys_map[f]) for dt in target_dts])
            else:
                std_field_arrs.append([None] * total_frames)
        else:
            std_field_arrs.append([None] * total_frames)
    t_std_ms = (time.perf_counter() - t0_std) * 1000.0

    # 6. Active FIT Fields
    t0_fit = time.perf_counter()
    fit_field_arrs: list[list] = []
    for name in active_fit:
        samples = _resolve_cache_samples(name, "fit")
        if samples:
            if name in ("speed", "enhanced_speed"):
                fit_field_arrs.append(_vectorize_linear_speed(samples, target_dts, target_ts_arr, ref_dt))
            elif name in ("distance", "dist", "track"):
                fit_field_arrs.append(_vectorize_linear_distance(samples, target_dts, target_ts_arr, ref_dt))
            elif name in ("alt", "enhanced_altitude", "altitude"):
                fit_field_arrs.append(_vectorize_linear_altitude(samples, target_dts, target_ts_arr, ref_dt))
            else:
                fit_field_arrs.append(_vectorize_step(samples, target_dts, target_ts_arr, ref_dt))
        elif resolve_cache_value is not None:
            fit_field_arrs.append([resolve_cache_value(name, "fit", dt, f"fit_{name}_text") for dt in target_dts])
        else:
            fit_field_arrs.append([None] * total_frames)
    t_fit_ms = (time.perf_counter() - t0_fit) * 1000.0

    # 7. Dynamic IMU Fields
    t0_imu = time.perf_counter()
    dynamic_field_arrs: list[list] = []
    for key in dynamic_keys:
        field_name = imu_fields[key][0]
        cfg = indicators.get(key, {})
        src = cfg.get("source", "gpmf")
        samples = _resolve_cache_samples(field_name, src)
        if samples:
            dynamic_field_arrs.append(_vectorize_step(samples, target_dts, target_ts_arr, ref_dt))
        elif resolve_cache_value is not None:
            dynamic_field_arrs.append([resolve_cache_value(field_name, src, dt, key) for dt in target_dts])
        else:
            dynamic_field_arrs.append([None] * total_frames)
    t_imu_ms = (time.perf_counter() - t0_imu) * 1000.0

    # 8. Record Assembly
    t0_records = time.perf_counter()
    elapsed_secs_arr = [
        max(0.0, (dt - start_dt_utc).total_seconds()) if start_dt_utc is not None else 0.0
        for dt in target_dts
    ]

    records: list[_FrameRec] = []
    num_std = len(std_field_arrs)
    num_fit = len(fit_field_arrs)
    num_dyn = len(dynamic_field_arrs)
    active_ind_keys = list(ind_arrs.keys())

    for i in range(total_frames):
        ind_vals = {k: ind_arrs[k][i] for k in active_ind_keys}

        dist_m = dist_arr[i]
        el_s = elapsed_secs_arr[i]
        avg_spd = (dist_m / el_s) * 3.6 if (el_s > 0 and dist_m is not None and dist_m > 0) else 0.0
        cur_pos = i / max(1, total_frames - 1) if total_frames > 1 else 0.0

        std_v = tuple(std_field_arrs[j][i] for j in range(num_std))
        fit_v = tuple(fit_field_arrs[j][i] for j in range(num_fit))
        dyn_v = tuple(dynamic_field_arrs[j][i] for j in range(num_dyn))

        records.append(_FrameRec(
            date_text=date_texts[i],
            time_text=time_texts[i],
            speed_value=speed_arr[i],
            distance_m=dist_m,
            alt_value=alt_arr[i],
            iso_value=iso_arr[i],
            exposure_value=exposure_arr[i],
            temp_value=temp_arr[i],
            indicator_values=ind_vals,
            fit_vals=fit_v,
            dynamic_vals=dyn_v,
            std_vals=std_v,
            current_position=cur_pos,
            elapsed_seconds=el_s,
            avg_speed_kmh=avg_spd,
            target_dt=target_dts[i],
        ))
    t_records_ms = (time.perf_counter() - t0_records) * 1000.0

    t_total_ms = (time.perf_counter() - t_start) * 1000.0

    if subtimer_dict is not None:
        subtimer_dict.update({
            "build_frame_times": t_timeline_ms,
            "build_step_fields": t_std_ms,
            "build_linear_fields": t_linear_ms,
            "build_dynamic_fit": t_fit_ms,
            "build_gpmf": t_gpmf_ms,
            "build_imu": t_imu_ms,
            "build_gps": t_static_ms,
            "build_distance": t_linear_ms * 0.33,
            "build_frame_rec": t_records_ms,
            "build_other": max(0.0, t_total_ms - (t_timeline_ms + t_std_ms + t_linear_ms + t_fit_ms + t_gpmf_ms + t_imu_ms + t_static_ms + t_records_ms)),
            "build_total_ms": t_total_ms,
        })

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
        records, static, t_total_ms, memory_bytes,
        len(active_fit) * total_frames, 3 * total_frames, 3 * total_frames,
    )

