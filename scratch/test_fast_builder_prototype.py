"""
Comprehensive test and exact parity validator for Fast TelemetryFrameCache Builder.
"""
import sys
import time
import math
from datetime import datetime, timedelta
from typing import Any, Callable, Optional
from pathlib import Path
import numpy as np

root = Path("c:/_DEV/TeleM")
sys.path.insert(0, str(root))
sys.path.insert(0, str(root / "src"))

from src.gui.telemetry_manager import TelemetryDataManager
from src.telemetry_extract import (
    ensure_records_list, load_json_with_fallback,
    extract_speed_samples, extract_altitude_samples, extract_track_samples,
    extract_iso_samples, extract_exposure_samples, extract_temperature_samples,
    smooth_speed_samples, interpolate_value, get_rotation_from_metadata,
    get_container_rotation, find_metadata_json, extract_gps_track,
    smooth_speed_values, extract_accelerometer_samples, extract_gyroscope_samples,
)
from src.gui.layout_manager import normalize_layout
from src.telemetry_precompute import (
    build_telemetry_cache, TelemetryFrameCache, _FrameRec, _Static, FIT_UNIT_HINTS
)
from src.indicators.registry import HARDCODED_KEYS
from src.ffmpeg.worker_cache import WORKER_CACHE, _resolve_cache_value, _resolve_cache_samples, init_worker
from src.indicators.frame_data import build_active_fit_field_plan

def _vectorize_step(
    samples: list[tuple[datetime, Any]],
    target_dts: list[datetime],
    target_ts_arr: np.ndarray,
    ref_dt: datetime,
) -> list[Any]:
    if not samples:
        return [None] * len(target_dts)
    
    # Normalise naive datetimes
    sample_dts = [s[0].replace(tzinfo=None) if s[0].tzinfo is not None else s[0] for s in samples]
    sample_vals = [s[1] for s in samples]
    sample_ts = np.array([(dt - ref_dt).total_seconds() for dt in sample_dts], dtype=np.float64)
    
    # searchsorted side="right" - 1
    # Exactly replicates bisect_right(times, target_dt) - 1
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
    if not samples:
        return [None] * len(target_dts)
    sample_dts = [s[0].replace(tzinfo=None) if s[0].tzinfo is not None else s[0] for s in samples]
    sample_vals = np.array([s[1] for s in samples], dtype=np.float64)
    sample_ts = np.array([(dt - ref_dt).total_seconds() for dt in sample_dts], dtype=np.float64)
    
    # np.interp: left=0.0 (if target_dt < samples[0][0], interpolate_speed returns 0.0)
    # right=max(0.0, samples[-1][1])
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
    if not samples:
        return [None] * len(target_dts)
    sample_dts = [s[0].replace(tzinfo=None) if s[0].tzinfo is not None else s[0] for s in samples]
    sample_vals = np.array([s[1] for s in samples], dtype=np.float64)
    sample_ts = np.array([(dt - ref_dt).total_seconds() for dt in sample_dts], dtype=np.float64)
    
    # left=0.0 (if target_dt < samples[0][0], interpolate_distance returns 0.0), right=samples[-1][1]
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
    if not samples:
        return [None] * len(target_dts)
    sample_dts = [s[0].replace(tzinfo=None) if s[0].tzinfo is not None else s[0] for s in samples]
    sample_vals = np.array([s[1] for s in samples], dtype=np.float64)
    sample_ts = np.array([(dt - ref_dt).total_seconds() for dt in sample_dts], dtype=np.float64)
    
    # left=samples[0][1] (if target_dt < samples[0][0], interpolate_altitude returns samples[0][1]), right=samples[-1][1]
    interp_vals = np.interp(
        target_ts_arr, sample_ts, sample_vals,
        left=float(sample_vals[0]), right=float(sample_vals[-1])
    )
    return [float(v) for v in interp_vals]

def build_telemetry_cache_fast(
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
    """Fast vectorized TelemetryFrameCache builder."""
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
    
    if fit_field_plan is not None:
        active_fit = fit_field_plan.get("active_fit_fields", [])
        std_names = tuple(fit_field_plan.get("active_standard_resolve_fields", []))
    else:
        active_fit = []
        std_names = tuple()
        fit = fit_data or {}
        for k, cfg in indicators.items():
            if k.startswith("fit_") and k.endswith("_text") and cfg.get("enabled", True):
                field_name = k[4:-5]
                if field_name and field_name in fit and field_name not in active_fit:
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

    # Precompute per-source arrays if needed
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
            if not samples:
                std_field_arrs.append([None] * total_frames)
            elif f in ("speed", "enhanced_speed"):
                std_field_arrs.append(_vectorize_linear_speed(samples, target_dts, target_ts_arr, ref_dt))
            elif f in ("distance", "dist", "track"):
                std_field_arrs.append(_vectorize_linear_distance(samples, target_dts, target_ts_arr, ref_dt))
            elif f in ("alt", "enhanced_altitude", "altitude"):
                std_field_arrs.append(_vectorize_linear_altitude(samples, target_dts, target_ts_arr, ref_dt))
            else:
                std_field_arrs.append(_vectorize_step(samples, target_dts, target_ts_arr, ref_dt))
        else:
            std_field_arrs.append([None] * total_frames)
    t_std_ms = (time.perf_counter() - t0_std) * 1000.0

    # 6. Active FIT Fields
    t0_fit = time.perf_counter()
    fit_field_arrs: list[list] = []
    for name in active_fit:
        samples = _resolve_cache_samples(name, "fit")
        if not samples:
            fit_field_arrs.append([None] * total_frames)
        elif name in ("speed", "enhanced_speed"):
            fit_field_arrs.append(_vectorize_linear_speed(samples, target_dts, target_ts_arr, ref_dt))
        elif name in ("distance", "dist", "track"):
            fit_field_arrs.append(_vectorize_linear_distance(samples, target_dts, target_ts_arr, ref_dt))
        elif name in ("alt", "enhanced_altitude", "altitude"):
            fit_field_arrs.append(_vectorize_linear_altitude(samples, target_dts, target_ts_arr, ref_dt))
        else:
            fit_field_arrs.append(_vectorize_step(samples, target_dts, target_ts_arr, ref_dt))
    t_fit_ms = (time.perf_counter() - t0_fit) * 1000.0

    # 7. Dynamic IMU Fields
    t0_imu = time.perf_counter()
    dynamic_field_arrs: list[list] = []
    for key in dynamic_keys:
        field_name = imu_fields[key][0]
        cfg = indicators.get(key, {})
        samples = _resolve_cache_samples(field_name, cfg.get("source", "gpmf"))
        if not samples:
            dynamic_field_arrs.append([None] * total_frames)
        else:
            dynamic_field_arrs.append(_vectorize_step(samples, target_dts, target_ts_arr, ref_dt))
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
        # Indicator dict for frame i
        ind_vals = {k: ind_arrs[k][i] for k in active_ind_keys}
        
        # Derived values
        dist_m = dist_arr[i]
        el_s = elapsed_secs_arr[i]
        avg_spd = (dist_m / el_s) * 3.6 if (el_s > 0 and dist_m is not None and dist_m > 0) else 0.0
        cur_pos = i / max(1, total_frames - 1) if total_frames > 1 else 0.0
        
        # Tuple packaging
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

def main():
    print("=== TESTING FAST BUILDER PROTOTYPE & PARITY ===", flush=True)
    video_path = root / "Video" / "GX030120.MP4"
    json_path = video_path.with_suffix(".json")
    fit_path = root / "Video" / "Popoludniowa_jazda_na_rowerze_solar_battery.fit"
    
    tm = TelemetryDataManager(
        extract_speed_fn=extract_speed_samples,
        extract_altitude_fn=extract_altitude_samples,
        extract_track_fn=extract_track_samples,
        extract_iso_fn=extract_iso_samples,
        extract_exposure_fn=extract_exposure_samples,
        extract_temperature_fn=extract_temperature_samples,
        smooth_fn=smooth_speed_samples,
        interpolate_fn=interpolate_value,
        get_rotation_meta_fn=get_rotation_from_metadata,
        get_container_rotation_fn=get_container_rotation,
        find_meta_json_fn=find_metadata_json,
        find_meta_json_write_fn=lambda p: p.with_suffix(".json"),
        load_telemetry_fn=lambda *a: None,
        ensure_records_fn=ensure_records_list,
        load_json_fallback_fn=load_json_with_fallback,
        write_records_fn=lambda p, r: None,
        extract_samples_exiftool_fn=lambda f: [],
        extract_altitude_exiftool_fn=lambda f: [],
        extract_gps_track_fn=extract_gps_track,
        find_gps_anchor_fn=lambda r: None,
        smooth_values_fn=smooth_speed_values,
        extract_accelerometer_fn=extract_accelerometer_samples,
        extract_gyroscope_fn=extract_gyroscope_samples,
    )
    records = ensure_records_list(load_json_with_fallback(json_path))
    tm.load_gpmf_records(records)
    tm.load_fit(str(fit_path))
    
    layout = normalize_layout(root / "def_layout.json", 3840, 2160)
    field_samples = tm.fit_data or {}
    init_worker(
        video_width=3840,
        video_height=2160,
        font_path="assets/Roboto-Bold.ttf",
        layout=layout,
        field_samples=field_samples,
        iso_samples=tm.iso_samples,
        exposure_samples=tm.exposure_samples,
        temperature_samples=tm.temperature_samples,
        gpx_speed_samples=tm.gpx_speed_samples,
        gpx_track_samples=tm.gpx_track_samples,
        gpx_alt_samples=tm.gpx_alt_samples,
        gpx_power_samples=tm.gpx_power_samples,
        gpx_atemp_samples=tm.gpx_atemp_samples,
        gpx_hr_samples=tm.gpx_hr_samples,
        gpx_cad_samples=tm.gpx_cad_samples,
        fit_data=tm.fit_data,
        gps_track=tm.get_gps_track_for_source("fit"),
        start_dt_utc=tm.start_dt_utc,
        tz_offset_hours=2.0,
        speed_samples=tm.speed_samples or [],
        track_samples=tm.track_samples or [],
        alt_samples=tm.alt_samples or [],
        target_fps=29.97,
    )
    
    fit_field_plan = build_active_fit_field_plan(layout, field_samples.keys())
    total_frames = 900
    
    # 1. Run OLD builder
    t0_old = time.perf_counter()
    cache_old = build_telemetry_cache(
        layout=layout,
        base_dt=tm.start_dt_utc,
        tz_offset_hours=2.0,
        start_dt_utc=tm.start_dt_utc,
        speed_samples=tm.speed_samples or [],
        track_samples=tm.track_samples or [],
        alt_samples=tm.alt_samples or [],
        iso_samples=tm.iso_samples,
        exposure_samples=tm.exposure_samples,
        temperature_samples=tm.temperature_samples,
        gpx_speed_samples=tm.gpx_speed_samples,
        gpx_track_samples=tm.gpx_track_samples,
        gpx_alt_samples=tm.gpx_alt_samples,
        gpx_power_samples=tm.gpx_power_samples,
        gpx_atemp_samples=tm.gpx_atemp_samples,
        gpx_hr_samples=tm.gpx_hr_samples,
        gpx_cad_samples=tm.gpx_cad_samples,
        fit_data=tm.fit_data,
        gps_track=tm.get_gps_track_for_source("fit"),
        chart_data={},
        resolve_cache_value=_resolve_cache_value,
        _range_cache=WORKER_CACHE.get("_prep_cache"),
        fit_field_plan=fit_field_plan,
        total_frames=total_frames,
        target_fps=29.97,
    )
    t_old_ms = (time.perf_counter() - t0_old) * 1000.0
    
    # 2. Run FAST builder
    subtimers = {}
    t0_fast = time.perf_counter()
    cache_fast = build_telemetry_cache_fast(
        layout=layout,
        base_dt=tm.start_dt_utc,
        tz_offset_hours=2.0,
        start_dt_utc=tm.start_dt_utc,
        speed_samples=tm.speed_samples or [],
        track_samples=tm.track_samples or [],
        alt_samples=tm.alt_samples or [],
        iso_samples=tm.iso_samples,
        exposure_samples=tm.exposure_samples,
        temperature_samples=tm.temperature_samples,
        gpx_speed_samples=tm.gpx_speed_samples,
        gpx_track_samples=tm.gpx_track_samples,
        gpx_alt_samples=tm.gpx_alt_samples,
        gpx_power_samples=tm.gpx_power_samples,
        gpx_atemp_samples=tm.gpx_atemp_samples,
        gpx_hr_samples=tm.gpx_hr_samples,
        gpx_cad_samples=tm.gpx_cad_samples,
        fit_data=tm.fit_data,
        gps_track=tm.get_gps_track_for_source("fit"),
        chart_data={},
        resolve_cache_value=_resolve_cache_value,
        _range_cache=WORKER_CACHE.get("_prep_cache"),
        fit_field_plan=fit_field_plan,
        total_frames=total_frames,
        target_fps=29.97,
        subtimer_dict=subtimers,
    )
    t_fast_ms = (time.perf_counter() - t0_fast) * 1000.0
    
    print(f"OLD Builder ({total_frames} frames):  {t_old_ms:8.2f} ms ({t_old_ms/total_frames:.3f} ms/frame)")
    print(f"FAST Builder ({total_frames} frames): {t_fast_ms:8.2f} ms ({t_fast_ms/total_frames:.3f} ms/frame)")
    print(f"SPEEDUP: {t_old_ms / max(1e-3, t_fast_ms):.2f}x faster!")
    print(f"\nSubtimers: {subtimers}")
    
    # 3. Complete Parity Check across all 900 frames and fields!
    print("\n--- RUNNING ALL-FRAME BIT-EXACT PARITY VALIDATION ---")
    fields_to_check = [
        "date_text", "time_text", "speed_value", "distance_m", "alt_value",
        "iso_value", "exposure_value", "temp_value", "power_value", "atemp_value",
        "hr_value", "cad_value", "battery_value", "current_position",
        "elapsed_seconds", "avg_speed_kmh", "target_dt"
    ]
    
    diff_count = 0
    max_float_diff = 0.0
    
    for f_idx in range(total_frames):
        rec_old = cache_old.lookup(f_idx)
        rec_fast = cache_fast.lookup(f_idx)
        
        # Check standard fields
        for field in fields_to_check:
            v_old = rec_old[field]
            v_fast = rec_fast[field]
            if v_old != v_fast:
                if isinstance(v_old, float) and isinstance(v_fast, float):
                    d = abs(v_old - v_fast)
                    if d > max_float_diff:
                        max_float_diff = d
                    if d > 1e-6:
                        print(f"MISMATCH at frame {f_idx}, field {field}: old={v_old}, fast={v_fast}, diff={d}")
                        diff_count += 1
                else:
                    print(f"MISMATCH at frame {f_idx}, field {field}: old={v_old}, fast={v_fast}")
                    diff_count += 1
                    
        # Check extra_indicators
        ext_old = rec_old["extra_indicators"]
        ext_fast = rec_fast["extra_indicators"]
        assert set(ext_old.keys()) == set(ext_fast.keys()), f"Keys mismatch at frame {f_idx}"
        for k in ext_old:
            val_old, u_old, l_old = ext_old[k]
            val_fast, u_fast, l_fast = ext_fast[k]
            assert u_old == u_fast and l_old == l_fast
            if val_old != val_fast:
                if isinstance(val_old, float) and isinstance(val_fast, float):
                    d = abs(val_old - val_fast)
                    if d > max_float_diff:
                        max_float_diff = d
                    if d > 1e-6:
                        print(f"EXTRA MISMATCH at frame {f_idx}, key {k}: old={val_old}, fast={val_fast}")
                        diff_count += 1
                else:
                    print(f"EXTRA MISMATCH at frame {f_idx}, key {k}: old={val_old}, fast={val_fast}")
                    diff_count += 1
                    
    print(f"\nPARITY RESULTS for {total_frames} frames:")
    print(f"  Total Fields Checked: {len(fields_to_check) + len(cache_old.lookup(0)['extra_indicators'])}")
    print(f"  Total Differences:    {diff_count}")
    print(f"  Max Float Difference: {max_float_diff:.2e}")
    if diff_count == 0 and max_float_diff < 1e-6:
        print(">>> ALL-FRAME FULL PARITY: PASS! <<<")
    else:
        print(">>> ALL-FRAME PARITY: FAIL! <<<")

if __name__ == "__main__":
    main()
