"""FFmpeg overlay rendering and encoding pipeline.

Handles building ffmpeg commands, rendering overlay frames via multiprocessing,
streaming frames directly to ffmpeg via pipe (producer-consumer), and applying
pre-rendered overlay videos.
"""

from __future__ import annotations

import io
import math
import os
import queue
import shlex
import subprocess
import threading
import time
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime, timedelta
from multiprocessing import shared_memory
from pathlib import Path
from typing import Any, Callable, Optional

from src.overlay_renderer import build_chart_data, compose_overlay
from src.telemetry_extract import (
    interpolate_altitude,
    interpolate_distance,
    interpolate_exposure,
    interpolate_iso,
    interpolate_speed,
    interpolate_temperature,
    interpolate_value,
)

# ── Globals ─────────────────────────────────────────────────────────────────

WORKER_CACHE: dict[str, Any] = {}

RESOLUTION_MAP: dict[str, tuple[int, int] | None] = {
    "source": None,
    "8k": (7680, 4320),
    "5.3k": (5312, 2988),
    "4k": (3840, 2160),
    "1080p": (1920, 1080),
    "720p": (1280, 720),
    "480p": (854, 480),
}

# Cached result of GPU decoder detection (None = CPU fallback)
_GPU_DECODER_CACHE: str | None | bool = False  # False = not yet checked


def _test_hwaccel(hwaccel: str) -> bool:
    """Test whether a given ``-hwaccel`` actually works by running a quick FFmpeg command.

    Returns ``True`` if the device can be initialised, ``False`` otherwise.
    """
    try:
        r = subprocess.run(
            [
                "ffmpeg", "-hide_banner", "-hwaccel", hwaccel,
                "-f", "lavfi", "-i", "color=c=black:s=352x288:d=0.1",
                "-f", "null", "-",
            ],
            capture_output=True, timeout=10,
            **({} if os.name != "nt" else {"startupinfo": _nt_startupinfo()}),
        )
        return r.returncode == 0
    except Exception:
        return False


def detect_gpu_decoder(preferred_encoder: str = "") -> str | None:
    """Return the best ``-hwaccel`` flag for this system, or ``None`` for CPU.

    If *preferred_encoder* is 'intel', prefers 'qsv' or 'd3d11va'.
    If *preferred_encoder* is 'nv', prefers 'cuda'.
    Checks NVIDIA (nvidia-smi), then queries ffmpeg -hwaccels for available
    hardware accelerators and validates each candidate with a short test.
    Result is cached per preferred encoder in ``_GPU_DECODER_CACHE``.
    """
    global _GPU_DECODER_CACHE
    cache_key = preferred_encoder.lower()
    if isinstance(_GPU_DECODER_CACHE, dict) and cache_key in _GPU_DECODER_CACHE:
        return _GPU_DECODER_CACHE[cache_key]

    if not isinstance(_GPU_DECODER_CACHE, dict):
        _GPU_DECODER_CACHE = {}

    selected_hw = None

    if preferred_encoder == "amd":
        for hw in ("d3d11va", "dxva2", "vulkan", "vaapi"):
            if _test_hwaccel(hw):
                selected_hw = hw
                break
    elif preferred_encoder == "intel":
        # On dual GPU systems (NVIDIA + Intel), '-hwaccel qsv' often locks up FFmpeg
        # when decoding input video in a pipe. 'd3d11va' / 'dxva2' work reliably on Intel GPU.
        for hw in ("d3d11va", "dxva2", "vulkan"):
            if _test_hwaccel(hw):
                selected_hw = hw
                break
    elif preferred_encoder == "nv":
        try:
            r = subprocess.run(
                ["nvidia-smi"], capture_output=True, timeout=5,
                **({} if os.name != "nt" else {"startupinfo": _nt_startupinfo()}),
            )
            if r.returncode == 0 and _test_hwaccel("cuda"):
                selected_hw = "cuda"
        except Exception:
            pass

    if selected_hw is None:
        # Fallback priority check
        for hw in ("cuda", "d3d11va", "dxva2", "qsv", "vaapi", "vulkan"):
            if _test_hwaccel(hw):
                selected_hw = hw
                break

    _GPU_DECODER_CACHE[cache_key] = selected_hw
    return selected_hw


def _nt_startupinfo() -> Any:
    """Return a STARTUPINFO that hides the console window on Windows."""
    si = subprocess.STARTUPINFO()
    si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    return si


def _test_encoder(encoder_name: str) -> bool:
    """Test whether a given encoder actually works by running a quick encode.

    Returns ``True`` if the encoder initialises successfully, ``False`` otherwise.
    """
    try:
        r = subprocess.run(
            [
                "ffmpeg", "-hide_banner",
                "-f", "lavfi", "-i", "color=c=black:s=352x288:d=0.1",
                "-c:v", encoder_name,
                "-f", "null", "-",
            ],
            capture_output=True, timeout=10,
            **({} if os.name != "nt" else {"startupinfo": _nt_startupinfo()}),
        )
        return r.returncode == 0
    except Exception:
        return False


def detect_best_encoder() -> str:
    """Detect the best available hardware encoder on this system.

    Returns one of ``'nv'`` (NVIDIA NVENC), ``'intel'`` (Intel QSV) or
    ``'cpu'`` (libx265 software).  Result is cached for subsequent calls.
    """
    global _GPU_DECODER_CACHE

    # Force detection if not yet done (do not use its result for encoding
    # decisions – we need a separate validation)
    detect_gpu_decoder()

    # Primary source of truth: check which encoders FFmpeg actually supports
    # and test each one to make sure the device is usable.
    try:
        r = subprocess.run(
            ["ffmpeg", "-hide_banner", "-encoders"],
            capture_output=True, text=True, timeout=5,
            **({} if os.name != "nt" else {"startupinfo": _nt_startupinfo()}),
        )
        if r.returncode == 0:
            encoders = r.stdout
            # Prefer NVIDIA NVENC, then AMD AMF, then Intel QSV
            if "hevc_nvenc" in encoders and _test_encoder("hevc_nvenc"):
                return "nv"
            if "hevc_amf" in encoders and _test_encoder("hevc_amf"):
                return "amd"
            if "h264_amf" in encoders and _test_encoder("h264_amf"):
                return "amd"
            if "hevc_qsv" in encoders and _test_encoder("hevc_qsv"):
                return "intel"
    except Exception:
        pass

    # Fallback: nvidia-smi + encoder test (nvidia-smi may exist without
    # full NVENC driver support, so test separately)
    try:
        r = subprocess.run(
            ["nvidia-smi"], capture_output=True, timeout=5,
            **({} if os.name != "nt" else {"startupinfo": _nt_startupinfo()}),
        )
        if r.returncode == 0 and _test_encoder("hevc_nvenc"):
            return "nv"
    except Exception:
        pass

    return "cpu"


# ── Worker cache initialisation ─────────────────────────────────────────────


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
) -> None:
    """Initialise WORKER_CACHE with all telemetry data for worker processes."""
    WORKER_CACHE["video_width"] = video_width
    WORKER_CACHE["video_height"] = video_height
    WORKER_CACHE["font_path"] = font_path
    WORKER_CACHE["layout"] = layout
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

    # Precompute chart data for workers (identical for every frame)
    WORKER_CACHE["_precomputed_chart_data"] = build_chart_data(
        layout, _get_source_samples, _resolve_cache_samples,
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
        trk_for_range = gpx_trk or trk
    elif dist_src == "fit":
        trk_for_range = fit_trk or trk
    else:
        trk_for_range = trk
    _prep_cache["max_distance_m"] = trk_for_range[-1][1] if trk_for_range else None

    # max_speed_kmh
    spd = speed_samples or []
    gpx_spd = gpx_speed_samples or []
    fit_spd = fit_data.get("speed", []) if fit_data else []
    spd_src = indic.get("speed_visual", {}).get("source", "gpmf")
    if spd_src == "gpx":
        spd_for_range = gpx_spd or spd
    elif spd_src == "fit":
        spd_for_range = fit_spd or spd
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
        alt_for_range = gpx_alt_s or alt_s
    elif alt_src == "fit":
        alt_for_range = fit_alt_s or alt_s
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


# ── Worker cache helpers ────────────────────────────────────────────────────


def _get_source_samples(source_type: str) -> tuple[list, list, list]:
    """Return (speed, track, alt) samples for the given source type."""
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
        return (gpx_spd or gpmf_spd, gpx_trk or gpmf_trk, gpx_alt or gpmf_alt)
    if source_type == "fit":
        return (fit_spd or gpmf_spd, fit_trk or gpmf_trk, fit_alt or gpmf_alt)
    return (gpmf_spd, gpmf_trk, gpmf_alt)


def _resolve_cache_value(
    field_name: str, target_dt: datetime, prefer: str = "fit"
) -> Any:
    """Return interpolated telemetry value from WORKER_CACHE with FIT > GPX > GPMF priority."""
    alt_prefix = "gpx" if prefer == "fit" else "fit"
    pref = WORKER_CACHE.get(f"{prefer}_{field_name}_samples", []) or []
    alt = WORKER_CACHE.get(f"{alt_prefix}_{field_name}_samples", []) or []
    samples = pref or alt

    # Also check fit_data dict (stored as WORKER_CACHE["fit_data"])
    if not samples and prefer == "fit":
        samples = WORKER_CACHE.get("fit_data", {}).get(field_name, []) or []
    if not samples and alt_prefix == "fit":
        samples = WORKER_CACHE.get("fit_data", {}).get(field_name, []) or []

    if not samples and field_name in (
        "speed", "alt", "dist", "track", "iso", "exposure", "temperature"
    ):
        if field_name in ("iso", "exposure", "temperature"):
            samples = WORKER_CACHE.get(f"{field_name}_samples", []) or []
        else:
            gpmf_key = "track_samples" if field_name in ("dist", "track") else f"{field_name}_samples"
            samples = WORKER_CACHE.get("field_samples", {}).get(gpmf_key, []) or []

    # FIT field-name alias fallback (e.g. "power" -> "curVpower")
    if not samples and prefer == "fit":
        _FIT_LOOKUP = {
            "power": ("curVpower",),
            "hr": ("heart_rate",),
            "cad": ("cadence",),
            "atemp": ("temperature",),
            "battery": ("battery_soc",),
        }
        for alias in _FIT_LOOKUP.get(field_name, ()):
            samples = WORKER_CACHE.get("fit_data", {}).get(alias, []) or []
            if samples:
                break

    if not samples:
        return None
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
    field_name: str, prefer: str = "fit"
) -> list:
    """Return raw sample list from WORKER_CACHE with FIT > GPX > GPMF priority."""
    alt_prefix = "gpx" if prefer == "fit" else "fit"
    pref = WORKER_CACHE.get(f"{prefer}_{field_name}_samples", []) or []
    alt = WORKER_CACHE.get(f"{alt_prefix}_{field_name}_samples", []) or []
    samples = pref or alt

    # Also check fit_data dict (stored as WORKER_CACHE["fit_data"])
    if not samples and prefer == "fit":
        samples = WORKER_CACHE.get("fit_data", {}).get(field_name, []) or []
    if not samples and alt_prefix == "fit":
        samples = WORKER_CACHE.get("fit_data", {}).get(field_name, []) or []

    if not samples and field_name in (
        "speed", "alt", "dist", "track", "iso", "exposure", "temperature"
    ):
        if field_name in ("iso", "exposure", "temperature"):
            samples = WORKER_CACHE.get(f"{field_name}_samples", []) or []
        else:
            gpmf_key = "track_samples" if field_name in ("dist", "track") else f"{field_name}_samples"
            samples = WORKER_CACHE.get("field_samples", {}).get(gpmf_key, []) or []

    # FIT field-name alias fallback (e.g. "power" -> "curVpower")
    if prefer == "fit":
        _FIT_LOOKUP = {
            "power": ("curVpower",),
            "hr": ("heart_rate",),
            "cad": ("cadence",),
            "atemp": ("temperature",),
            "battery": ("battery_soc",),
        }
        for alias in _FIT_LOOKUP.get(field_name, ()):
            candidate = WORKER_CACHE.get("fit_data", {}).get(alias, []) or []
            if candidate:
                samples = candidate
                break

    return samples


# ── Single overlay frame (disk-based) ───────────────────────────────────────


def render_overlay_job(job: tuple) -> int:
    """Render one overlay frame to disk (BMP). Used by ProcessPoolExecutor."""
    if len(job) == 9:
        (index, overlay_dir_text, start_dt_utc, tz_offset_hours,
         speed_samples, track_samples, alt_samples, target_fps, update_rate_step) = job
    else:
        (index, overlay_dir_text, start_dt_utc, tz_offset_hours,
         speed_samples, track_samples, alt_samples, target_fps) = job
        update_rate_step = 1
    overlay_dir = Path(overlay_dir_text)
    video_width = WORKER_CACHE["video_width"]
    video_height = WORKER_CACHE["video_height"]
    font_path = WORKER_CACHE["font_path"]
    layout = WORKER_CACHE["layout"]
    max_distance_m = WORKER_CACHE.get("max_distance_m", 1000.0)
    iso_samples = WORKER_CACHE.get("iso_samples", [])
    exposure_samples = WORKER_CACHE.get("exposure_samples", [])
    temperature_samples = WORKER_CACHE.get("temperature_samples", [])
    sample_t = (index * update_rate_step) / target_fps
    t0 = start_dt_utc if start_dt_utc is not None else speed_samples[0][0]
    current_dt_utc = t0 + timedelta(seconds=sample_t)
    current_dt_local = current_dt_utc + timedelta(hours=tz_offset_hours)

    indicator_values: dict[str, float] = {}
    for ind_key in ("speed_visual", "speed_text", "dist_visual", "dist_text", "alt_visual", "alt_text"):
        ind_cfg = layout["indicators"].get(ind_key, {})
        src = ind_cfg.get("source", "gpmf")
        gpx_spd = WORKER_CACHE.get("gpx_speed_samples", [])
        gpx_trk = WORKER_CACHE.get("gpx_track_samples", [])
        gpx_alt = WORKER_CACHE.get("gpx_alt_samples", [])
        fit_spd = WORKER_CACHE.get("fit_data", {}).get("speed", [])
        fit_trk = WORKER_CACHE.get("fit_data", {}).get("track", [])
        fit_alt = WORKER_CACHE.get("fit_data", {}).get("alt", [])
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
            indicator_values[ind_key] = interpolate_speed(spd_s, current_dt_utc)
        elif ind_key in ("dist_visual", "dist_text"):
            indicator_values[ind_key] = interpolate_distance(trk_s, current_dt_utc)
        elif ind_key in ("alt_visual", "alt_text"):
            indicator_values[ind_key] = interpolate_altitude(alt_s, current_dt_utc)

    iso_value = interpolate_iso(iso_samples, current_dt_utc)
    exposure_value = interpolate_exposure(exposure_samples, current_dt_utc)
    temp_value = interpolate_temperature(temperature_samples, current_dt_utc)

    power_value = _resolve_cache_value("power", current_dt_utc)
    atemp_value = _resolve_cache_value("atemp", current_dt_utc)
    hr_value = _resolve_cache_value("hr", current_dt_utc)
    cad_value = _resolve_cache_value("cad", current_dt_utc)
    battery_value = _resolve_cache_value("battery", current_dt_utc)

    speed_value = indicator_values.get("speed_visual", interpolate_speed(speed_samples, current_dt_utc))
    distance_m = indicator_values.get("dist_visual", interpolate_distance(track_samples, current_dt_utc))
    alt_value = indicator_values.get("alt_visual", interpolate_altitude(alt_samples, current_dt_utc))

    dist_src = layout["indicators"].get("dist_visual", {}).get("source", "gpmf")
    if dist_src == "gpx":
        gpx_trk = WORKER_CACHE.get("gpx_track_samples", [])
        if gpx_trk:
            max_distance_m = gpx_trk[-1][1]
    elif dist_src == "fit":
        fit_trk = WORKER_CACHE.get("fit_data", {}).get("track", [])
        if fit_trk:
            max_distance_m = fit_trk[-1][1]

    max_speed_kmh: Optional[float] = None
    spd_src = layout["indicators"].get("speed_visual", {}).get("source", "gpmf")
    if spd_src == "gpx":
        gpx_spd_w = WORKER_CACHE.get("gpx_speed_samples", [])
        spd_for_range = gpx_spd_w or speed_samples
    elif spd_src == "fit":
        fit_spd_w = WORKER_CACHE.get("fit_data", {}).get("speed", [])
        spd_for_range = fit_spd_w or speed_samples
    else:
        spd_for_range = speed_samples
    if spd_for_range:
        spd_vals = [s for _, s in spd_for_range]
        if spd_vals:
            max_speed_kmh = max(spd_vals)

    min_alt: Optional[float] = None
    max_alt: Optional[float] = None
    alt_src = layout["indicators"].get("alt_visual", {}).get("source", "gpmf")
    if alt_src == "gpx":
        gpx_alt_w = WORKER_CACHE.get("gpx_alt_samples", [])
        alt_for_range = gpx_alt_w or alt_samples
    elif alt_src == "fit":
        fit_alt_w = WORKER_CACHE.get("fit_data", {}).get("alt", [])
        alt_for_range = fit_alt_w or alt_samples
    else:
        alt_for_range = alt_samples
    if alt_for_range:
        alts = [a for _, a in alt_for_range]
        if alts:
            min_alt = min(alts)
            max_alt = max(alts)

    date_text = current_dt_local.strftime("%Y-%m-%d")
    time_text = current_dt_local.strftime("%H:%M:%S")

    total_frames = WORKER_CACHE.get("total_overlay_frames", 1)
    current_position = index / max(1, total_frames - 1) if total_frames > 1 else 0.0
    chart_data = WORKER_CACHE.get("_precomputed_chart_data", {})

    # Build extra indicators – MUST match _render_preview in controller.py
    _HARDCODED_KEYS = {
        "speed_visual", "speed_text", "dist_visual", "dist_text",
        "alt_visual", "alt_text", "iso_text", "exposure_text",
        "temp_text", "power_text", "atemp_text", "hr_text",
        "cad_text", "battery_text", "track_map", "time_block",
    }
    extra_indicators: dict[str, tuple[float, str, str]] = {}
    # 1) FIT fields – resolve real values from telemetry
    for ind_key, ind_cfg in layout.get("indicators", {}).items():
        if ind_key.startswith("fit_") and ind_key.endswith("_text"):
            field_name = ind_key[4:-5]
            fit_val = _resolve_cache_value(field_name, current_dt_utc) or 0.0
            extra_indicators[ind_key] = (fit_val, ind_cfg.get("unit", ""), ind_cfg.get("label", field_name))
    # 2) All remaining dynamic indicators (non-hardcoded, not already captured)
    for ind_key in list(layout.get("indicators", {}).keys()):
        if ind_key in _HARDCODED_KEYS or ind_key in extra_indicators:
            continue
        ind_cfg = layout["indicators"][ind_key]
        extra_indicators[ind_key] = (0.0, ind_cfg.get("unit", ""), ind_cfg.get("label", ind_key))

    # ── Elapsed time & average speed (for time_display) ───────────────
    _elapsed = 0.0
    if start_dt_utc is not None and current_dt_utc is not None:
        _elapsed = max(0.0, (current_dt_utc - start_dt_utc).total_seconds())
    _avg_spd = 0.0
    if _elapsed > 0 and distance_m > 0:
        _avg_spd = (distance_m / _elapsed) * 3.6

    img = compose_overlay(
        video_width, video_height, layout, font_path, date_text, time_text,
        speed_value, distance_m, max_distance_m, alt_value,
        min_alt, max_alt, iso_value, exposure_value, temp_value,
        indicator_values=indicator_values, max_speed_kmh=max_speed_kmh,
        power_value=power_value, atemp_value=atemp_value,
        hr_value=hr_value, cad_value=cad_value,
        battery_value=battery_value,
        chart_data=chart_data, current_position=current_position,
        extra_indicators=extra_indicators,
        gps_track=WORKER_CACHE.get("gps_track", []),
        target_dt=current_dt_utc,
        start_dt_utc=start_dt_utc,
        elapsed_seconds=_elapsed,
        avg_speed_kmh=_avg_spd,
    )
    rot = WORKER_CACHE.get("effective_rotation", 0) % 360
    if rot == 180:
        from PIL import Image
        img = img.transpose(Image.ROTATE_180)
    elif rot == 90:
        from PIL import Image
        img = img.transpose(Image.ROTATE_270)
    elif rot == 270:
        from PIL import Image
        img = img.transpose(Image.ROTATE_90)
    img.save(overlay_dir / f"overlay_{index:06d}.bmp", format="BMP")
    return index


# ── Overlay sequence generation (disk-based) ────────────────────────────────


def generate_overlay_sequence(
    overlay_dir: Path,
    duration_s: float,
    video_width: int,
    video_height: int,
    start_dt_utc: Optional[datetime],
    tz_offset_hours: float,
    speed_samples: list,
    track_samples: list,
    alt_samples: list,
    font_path: str,
    layout: dict[str, Any],
    field_samples: dict[str, Any],
    target_fps: float = 30.0,
    workers: Optional[int] = None,
    max_distance_m: Optional[float] = None,
    progress_cb: Optional[Callable] = None,
    cancel_event: Optional[Any] = None,
    update_rate_step: int = 1,
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
) -> int:
    """Generate overlay frames as BMP files using multiprocessing."""
    overlay_dir.mkdir(parents=True, exist_ok=True)
    generation_fps = target_fps / update_rate_step
    total_overlay_frames = max(1, math.ceil(duration_s * generation_fps))
    if cancel_event is not None and cancel_event.is_set():
        return 0
    workers = workers or max(1, (os.cpu_count() or 1) - 1)
    jobs = [
        (i, str(overlay_dir), start_dt_utc, tz_offset_hours,
         speed_samples, track_samples, alt_samples, target_fps, update_rate_step)
        for i in range(total_overlay_frames)
    ]
    start_time = time.time()

    WORKER_CACHE["total_overlay_frames"] = total_overlay_frames

    progress_interval = max(1, min(3, total_overlay_frames // 1000))
    if workers <= 1:
        init_worker(
            video_width, video_height, font_path, layout, field_samples, max_distance_m,
            iso_samples, exposure_samples, temperature_samples,
            gpx_speed_samples, gpx_track_samples, gpx_alt_samples,
            gpx_power_samples, gpx_atemp_samples, gpx_hr_samples, gpx_cad_samples,
            fit_data=fit_data,
            gps_track=gps_track,
            start_dt_utc=start_dt_utc, tz_offset_hours=tz_offset_hours,
            speed_samples=speed_samples, track_samples=track_samples,
            alt_samples=alt_samples, target_fps=target_fps,
            update_rate_step=update_rate_step,
        )
        for i, job in enumerate(jobs, start=1):
            if cancel_event is not None and cancel_event.is_set():
                return i - 1
            render_overlay_job(job)
            if i % progress_interval == 0 or i == total_overlay_frames:
                elapsed = time.time() - start_time
                m, s = divmod(int(elapsed), 60)
                h, m = divmod(m, 60)
                fps = i / elapsed if elapsed > 0 else 0
                stats = f"PNG: {i}/{total_overlay_frames} | fps: {fps:.1f} | elapse: {h:02d}:{m:02d}:{s:02d}"
                if progress_cb:
                    progress_cb(i, stats)
        return total_overlay_frames

    done = 0
    with ProcessPoolExecutor(
        max_workers=workers,
        initializer=init_worker,
        initargs=(
            video_width, video_height, font_path, layout, field_samples, max_distance_m,
            iso_samples, exposure_samples, temperature_samples,
            gpx_speed_samples, gpx_track_samples, gpx_alt_samples,
            gpx_power_samples, gpx_atemp_samples, gpx_hr_samples, gpx_cad_samples,
            fit_data,
            gps_track,
            start_dt_utc, tz_offset_hours,
            speed_samples, track_samples, alt_samples,
            target_fps, update_rate_step,
        ),
    ) as ex:
        chunk = max(1, total_overlay_frames // max(1, workers * 4))
        for _ in ex.map(render_overlay_job, jobs, chunksize=chunk):
            if cancel_event is not None and cancel_event.is_set():
                try:
                    ex.shutdown(wait=False, cancel_futures=True)
                except Exception:
                    pass
                break
            done += 1
            if done % progress_interval == 0 or done == total_overlay_frames:
                elapsed = time.time() - start_time
                m, s = divmod(int(elapsed), 60)
                h, m = divmod(m, 60)
                fps = done / elapsed if elapsed > 0 else 0
                stats = f"PNG: {done}/{total_overlay_frames} | fps: {fps:.1f} | elapse: {h:02d}:{m:02d}:{s:02d}"
                if progress_cb:
                    progress_cb(done, stats)
        try:
            if cancel_event is not None and cancel_event.is_set():
                ex.shutdown(wait=False, cancel_futures=True)
        except Exception:
            pass
        return done


# ── Build overlay video from pre-rendered frames ────────────────────────────


def build_overlay_video(
    ffmpeg_exe: str,
    overlay_dir: Path,
    overlay_video_path: str,
    fps: float = 30.0,
    total_frames: Optional[int] = None,
    progress_cb: Optional[Callable] = None,
    cancel_event: Optional[Any] = None,
    active_process_holder: Optional[dict] = None,
) -> None:
    """Build a ProRes overlay video from rendered BMP frames."""
    cmd = [
        ffmpeg_exe, "-y", "-framerate", str(fps),
        "-i", str(overlay_dir / "overlay_%06d.bmp"),
        "-c:v", "qtrle", "-pix_fmt", "argb", str(overlay_video_path),
    ]
    if progress_cb and total_frames:
        run_ffmpeg_with_progress(
            cmd, total_frames, progress_cb, "MOV",
            cancel_event=cancel_event, active_process_holder=active_process_holder,
        )
    else:
        if cancel_event is not None and cancel_event.is_set():
            return
        p = subprocess.run(cmd)
        if p.returncode != 0:
            raise RuntimeError(f"Command failed with exit code {p.returncode}")


# ── Stream FFmpeg command builder ───────────────────────────────────────────


def _build_stream_ffmpeg_cmd(
    ffmpeg_exe: str,
    input_args: list[str],
    output_file: str,
    overlay_w: int,
    overlay_h: int,
    generation_fps: float,
    encoder: str,
    gpu: int,
    video_bitrate: str,
    render_w: int,
    render_h: int,
    resolution_name: str,
    container_rotation: int,
    rotation_degrees: int,
    hwaccel: str | None = None,
    cut_regions: list[tuple[float, float]] | None = None,
    audio_input_args: list[str] | None = None,
) -> tuple[list[str], str]:
    """Build the ffmpeg command for the streaming pipeline.

    When *hwaccel* is ``"cuda"`` and no rotation is needed, the GPU
    ``overlay_cuda`` filter is used so that compositing runs on the GPU.
    When rotation is required the caller skips ``-hwaccel`` entirely so
    that decoding, overlay and rotation all happen on the CPU without
    format-negotiation issues between ``hflip`` and the encoder.
    """
    target_res = RESOLUTION_MAP.get(resolution_name)

    # ── Base filter (video scaling) ─────────────────────────────────────
    if target_res and encoder == "nv":
        # GPU scaling
        base_filter = (
            f"[0:v]hwupload_cuda,scale_cuda={render_w}:{render_h}[base]"
        )
    elif target_res:
        base_filter = f"[0:v]scale={render_w}:{render_h}:flags=lanczos[base]"
    else:
        base_filter = "[0:v]null[base]"

    # ── Overlay stream & operator ───────────────────────────────────────
    if overlay_w != render_w or overlay_h != render_h:
        ov_input = f"[1:v]setpts=PTS-STARTPTS,format=rgba,scale={render_w}:{render_h}:flags=bilinear[ov]"
    else:
        ov_input = "[1:v]setpts=PTS-STARTPTS,format=rgba[ov]"
    ov_op = "overlay"

    filter_complex = (
        f"{base_filter};{ov_input};"
        f"[base][ov]{ov_op}=0:0:shortest=1[vtemp]"
    )

    # ── Cut region drop (select filter) ────────────────────────────────
    has_cuts = bool(cut_regions and len(cut_regions) > 0)
    if has_cuts:
        # Build select/aselect expression: drop frames in cut regions
        parts = []
        for cs, ce in cut_regions:
            parts.append(f"between(t,{cs},{ce})")
        select_expr = "not(" + "+".join(parts) + ")"
        filter_complex += (
            f";[vtemp]select='{select_expr}',setpts=N/FRAME_RATE/TB[vout]"
        )
        # Audio: aselect – tnie ścieżkę audio tak samo jak wideo
        audio_idx = "2" if audio_input_args else "0"
        filter_complex += (
            f";[{audio_idx}:a]aselect='{select_expr}',asetpts=N/SR/TB[aout]"
        )
        print(f"[CUT] select filter: {select_expr}", flush=True)
    else:
        filter_complex += ";[vtemp]null[vout]"

    cmd: list[str] = [
        ffmpeg_exe, "-y",
        *input_args,
        "-f", "rawvideo", "-pix_fmt", "rgba",
        "-s", f"{overlay_w}x{overlay_h}",
        "-r", str(generation_fps),
        "-i", "pipe:0",
    ]
    if audio_input_args:
        cmd.extend(audio_input_args)
    cmd.extend([
        "-filter_complex", filter_complex,
        "-map", "[vout]",
    ])

    if has_cuts:
        # Gdy są cięcia – audio przechodzi przez aselect, potrzebuje re-encoda
        cmd.extend(["-map", "[aout]?"])
    else:
        # Bez cięć – audio kopiowane wprost z pliku
        audio_idx = "2" if audio_input_args else "0"
        cmd.extend(["-map", f"{audio_idx}:a?"])

    effective_rotation = container_rotation if container_rotation != 0 else rotation_degrees
    cmd.extend([
        "-map_metadata", "-1", "-metadata:s:v:0", f"rotate={effective_rotation}",
    ])

    if encoder == "nv":
        cmd.extend([
            "-c:v", "hevc_nvenc", "-preset", "p1", "-tune", "hq", "-rc", "vbr",
            "-cq", "24", "-pix_fmt", "yuv420p", "-gpu", str(gpu),
        ])
        if has_cuts:
            cmd.extend(["-c:a", "aac", "-b:a", "192k"])
        else:
            cmd.extend(["-c:a", "copy"])
    elif encoder == "amd":
        amf_encoder = "hevc_amf" if _test_encoder("hevc_amf") else "h264_amf"
        cmd.extend([
            "-c:v", amf_encoder, "-usage", "transcoding", "-quality", "speed",
            "-rc", "cbr", "-pix_fmt", "nv12",
        ])
        if has_cuts:
            cmd.extend(["-c:a", "aac", "-b:a", "192k"])
        else:
            cmd.extend(["-c:a", "copy"])
    elif encoder == "intel":
        cmd.extend([
            "-c:v", "hevc_qsv", "-preset", "veryfast",
            "-global_quality", "24", "-look_ahead", "0",
            "-async_depth", "4", "-pix_fmt", "nv12",
        ])
        if has_cuts:
            cmd.extend(["-c:a", "aac", "-b:a", "192k"])
        else:
            cmd.extend(["-c:a", "copy"])
    else:
        cmd.extend([
            "-c:v", "libx265", "-preset", "medium", "-crf", "24",
            "-pix_fmt", "yuv420p",
        ])
        if has_cuts:
            cmd.extend(["-c:a", "aac", "-b:a", "192k"])
        else:
            cmd.extend(["-c:a", "copy"])

    cmd = append_bitrate_args(cmd, encoder, video_bitrate)
    cmd.append(str(output_file))
    cmd.extend(["-progress", "pipe:1", "-nostats", "-loglevel", "error"])
    return cmd, filter_complex


# ── Single overlay frame (streaming / memory) ────────────────────────────────


def render_overlay_frame(
    index: int,
    start_dt_utc: Optional[datetime],
    tz_offset_hours: float,
    speed_samples: list,
    track_samples: list,
    alt_samples: list,
    target_fps: float,
    update_rate_step: int = 1,
) -> Any:
    """Render a single overlay frame – returns PIL Image RGBA. Uses WORKER_CACHE."""
    video_width = WORKER_CACHE["video_width"]
    video_height = WORKER_CACHE["video_height"]

    # ── Wczesny return: klatka w wyciętym fragmencie → pusta nakładka ──
    sample_t = (index * update_rate_step) / target_fps
    current_t = sample_t
    cut_regions = WORKER_CACHE.get("_cut_regions", [])
    for cut_start, cut_end in cut_regions:
        if cut_start <= current_t < cut_end:
            from PIL import Image
            return Image.new("RGBA", (video_width, video_height), (0, 0, 0, 0))

    font_path = WORKER_CACHE["font_path"]
    layout = WORKER_CACHE["layout"]
    iso_samples = WORKER_CACHE.get("iso_samples", [])
    exposure_samples = WORKER_CACHE.get("exposure_samples", [])
    temperature_samples = WORKER_CACHE.get("temperature_samples", [])

    t0 = start_dt_utc
    if t0 is None:
        fallback_lists = [
            speed_samples, track_samples, alt_samples,
            WORKER_CACHE.get("gpx_speed_samples"),
            WORKER_CACHE.get("gpx_track_samples"),
            WORKER_CACHE.get("gpx_alt_samples"),
        ]
        fit_dict = WORKER_CACHE.get("fit_data")
        if fit_dict and isinstance(fit_dict, dict):
            fallback_lists.extend(fit_dict.values())

        for lst in fallback_lists:
            if lst and len(lst) > 0 and lst[0] and len(lst[0]) > 0:
                t0 = lst[0][0]
                break
        if t0 is None:
            from datetime import timezone
            t0 = datetime(1970, 1, 1, tzinfo=timezone.utc)

    # Upewnij się, że t0 to datetime (konwertuj float/int sekundy z epoch na datetime)
    if not isinstance(t0, datetime):
        from datetime import timezone
        try:
            t0 = datetime.fromtimestamp(float(t0), timezone.utc)
        except Exception:
            t0 = datetime(1970, 1, 1, tzinfo=timezone.utc)

    current_dt_utc = t0 + timedelta(seconds=sample_t)

    total_frames = WORKER_CACHE.get("total_overlay_frames", 1)
    chart_data = WORKER_CACHE.get("_precomputed_chart_data", {})

    from src.overlay_renderer import prepare_overlay_frame_data
    data = prepare_overlay_frame_data(
        layout=layout,
        target_dt=current_dt_utc,
        tz_offset_hours=tz_offset_hours,
        start_dt_utc=start_dt_utc,
        speed_samples=speed_samples,
        track_samples=track_samples,
        alt_samples=alt_samples,
        iso_samples=iso_samples,
        exposure_samples=exposure_samples,
        temperature_samples=temperature_samples,
        gpx_speed_samples=WORKER_CACHE.get("gpx_speed_samples"),
        gpx_track_samples=WORKER_CACHE.get("gpx_track_samples"),
        gpx_alt_samples=WORKER_CACHE.get("gpx_alt_samples"),
        gpx_power_samples=WORKER_CACHE.get("gpx_power_samples"),
        gpx_atemp_samples=WORKER_CACHE.get("gpx_atemp_samples"),
        gpx_hr_samples=WORKER_CACHE.get("gpx_hr_samples"),
        gpx_cad_samples=WORKER_CACHE.get("gpx_cad_samples"),
        fit_data=WORKER_CACHE.get("fit_data"),
        gps_track=WORKER_CACHE.get("gps_track"),
        total_frames=total_frames,
        current_index=index,
        chart_data=chart_data,
        resolve_cache_value=_resolve_cache_value,
        _range_cache=WORKER_CACHE.get("_prep_cache"),
    )

    img = compose_overlay(
        video_width, video_height, layout, font_path,
        data["date_text"], data["time_text"],
        data["speed_value"], data["distance_m"], data["max_distance_m"],
        data["alt_value"], data["min_alt"], data["max_alt"],
        data["iso_value"], data["exposure_value"], data["temp_value"],
        indicator_values=data["indicator_values"],
        max_speed_kmh=data["max_speed_kmh"],
        power_value=data["power_value"],
        atemp_value=data["atemp_value"],
        hr_value=data["hr_value"],
        cad_value=data["cad_value"],
        battery_value=data["battery_value"],
        chart_data=data["chart_data"],
        current_position=data["current_position"],
        extra_indicators=data["extra_indicators"],
        gps_track=data["gps_track"],
        target_dt=data["target_dt"],
        start_dt_utc=data["start_dt_utc"],
        elapsed_seconds=data["elapsed_seconds"],
        avg_speed_kmh=data["avg_speed_kmh"],
    )
    rot = WORKER_CACHE.get("effective_rotation", 0) % 360
    if rot == 180:
        from PIL import Image
        img = img.transpose(Image.ROTATE_180)
    elif rot == 90:
        from PIL import Image
        img = img.transpose(Image.ROTATE_270)
    elif rot == 270:
        from PIL import Image
        img = img.transpose(Image.ROTATE_90)
    return img


# ── Frame bytes job (streaming worker) ──────────────────────────────────────


def render_frame_bytes_job(job: tuple) -> tuple[int, bytes]:
    """Multiprocessing worker: render one overlay frame, return (index, raw_rgba_bytes)."""
    index = job[0]
    start_dt_utc = WORKER_CACHE.get("start_dt_utc")
    tz_offset_hours = WORKER_CACHE.get("tz_offset_hours")
    speed_samples = WORKER_CACHE.get("speed_samples")
    track_samples = WORKER_CACHE.get("track_samples")
    alt_samples = WORKER_CACHE.get("alt_samples")
    target_fps = WORKER_CACHE.get("target_fps")
    update_rate_step = WORKER_CACHE.get("update_rate_step", 1)
    img = render_overlay_frame(
        index, start_dt_utc, tz_offset_hours,
        speed_samples, track_samples, alt_samples,
        target_fps, update_rate_step,
    )
    # Raw RGBA bytes — no PNG encode/decode overhead
    return index, img.tobytes()


# ── Shared Memory frame pool ────────────────────────────────────────────────
#
# Eliminates the ~33 MB pickle IPC overhead per 4K RGBA frame by writing
# rendered frame bytes directly into pre-allocated shared memory blocks.
# The worker returns only (index, shm_slot_id) — ~50 bytes via pickle
# instead of 33 MB.


class SharedFramePool:
    """Pool of pre-allocated shared memory blocks for zero-copy IPC.

    Each slot holds one raw RGBA frame (overlay_w × overlay_h × 4 bytes).
    Workers acquire a slot, write frame data, and release it after the
    main thread has consumed it.
    """

    def __init__(self, n_slots: int, frame_size_bytes: int) -> None:
        self.n_slots = n_slots
        self.frame_size = frame_size_bytes
        self._shm_blocks: list[shared_memory.SharedMemory] = []
        self._free: queue.Queue[int] = queue.Queue()
        for i in range(n_slots):
            shm = shared_memory.SharedMemory(create=True, size=frame_size_bytes)
            self._shm_blocks.append(shm)
            self._free.put(i)

    def shm_names(self) -> list[str]:
        """Return list of SHM block names (for passing to worker processes)."""
        return [shm.name for shm in self._shm_blocks]

    def acquire(self, timeout: float = 30.0) -> int:
        """Acquire a free slot index (blocks until one is available)."""
        return self._free.get(timeout=timeout)

    def release(self, slot: int) -> None:
        """Release a slot back to the free pool."""
        self._free.put(slot)

    def read(self, slot: int) -> bytes:
        """Read raw frame bytes from a slot (zero-copy via memoryview)."""
        return bytes(self._shm_blocks[slot].buf[:self.frame_size])

    def read_into(self, slot: int, dest: Any) -> None:
        """Write slot contents directly to a writable file-like object."""
        dest.write(self._shm_blocks[slot].buf[:self.frame_size])

    def close(self) -> None:
        """Close and unlink all shared memory blocks."""
        for shm in self._shm_blocks:
            try:
                shm.close()
                shm.unlink()
            except Exception:
                pass
        self._shm_blocks.clear()


# Global references set by worker initialiser — one per child process.
_SHM_BLOCKS: list[shared_memory.SharedMemory | None] = []
_SHM_FRAME_SIZE: int = 0


def _init_shm_in_worker(shm_names: list[str], frame_size: int) -> None:
    """Attach to existing shared memory blocks in a child worker process."""
    global _SHM_BLOCKS, _SHM_FRAME_SIZE
    _SHM_FRAME_SIZE = frame_size
    _SHM_BLOCKS = []
    for name in shm_names:
        _SHM_BLOCKS.append(shared_memory.SharedMemory(name=name, create=False))


def _close_shm_in_worker() -> None:
    """Detach from shared memory (called at worker shutdown via atexit)."""
    global _SHM_BLOCKS
    for shm in _SHM_BLOCKS:
        if shm is not None:
            try:
                shm.close()
            except Exception:
                pass
    _SHM_BLOCKS = []


def _init_worker_with_shm(
    shm_names: list[str], frame_size: int,
    *init_worker_args: Any,
) -> None:
    """Combined initialiser: set up WORKER_CACHE + attach SHM blocks."""
    import atexit
    init_worker(*init_worker_args)
    _init_shm_in_worker(shm_names, frame_size)
    atexit.register(_close_shm_in_worker)


def render_frame_shm_job(job: tuple) -> tuple[int, int]:
    """Render one overlay frame into a shared memory slot.

    Args:
        job: (frame_index, shm_slot_id)

    Returns:
        (frame_index, shm_slot_id) — only ~50 bytes through pickle.
    """
    index, slot = job
    start_dt_utc = WORKER_CACHE.get("start_dt_utc")
    tz_offset_hours = WORKER_CACHE.get("tz_offset_hours")
    speed_samples = WORKER_CACHE.get("speed_samples")
    track_samples = WORKER_CACHE.get("track_samples")
    alt_samples = WORKER_CACHE.get("alt_samples")
    target_fps = WORKER_CACHE.get("target_fps")
    update_rate_step = WORKER_CACHE.get("update_rate_step", 1)
    img = render_overlay_frame(
        index, start_dt_utc, tz_offset_hours,
        speed_samples, track_samples, alt_samples,
        target_fps, update_rate_step,
    )
    raw = img.tobytes()
    _SHM_BLOCKS[slot].buf[:_SHM_FRAME_SIZE] = raw
    return index, slot


# ── Async pipe writer thread ────────────────────────────────────────────────


def _pipe_writer_thread(
    write_queue: queue.Queue,
    stdin_buffer: Any,
    done_event: threading.Event,
) -> None:
    """Background thread that drains frame bytes to FFmpeg stdin pipe.

    Receives (bytes_data,) from write_queue and writes to stdin_buffer.
    Terminates when done_event is set and queue is empty, or on None sentinel.
    """
    try:
        while True:
            try:
                item = write_queue.get(timeout=0.5)
            except queue.Empty:
                if done_event.is_set():
                    break
                continue
            if item is None:  # sentinel
                break
            stdin_buffer.write(item)
    except (BrokenPipeError, OSError):
        pass


# ── Streaming pipeline (producer-consumer) ──────────────────────────────────


def stream_overlay_to_ffmpeg(
    ffmpeg_exe: str,
    input_files: list,
    output_file: str,
    duration_s: float,
    start_dt_utc: Optional[datetime],
    tz_offset_hours: float,
    speed_samples: list,
    track_samples: list,
    alt_samples: list,
    font_path: str,
    layout: dict[str, Any],
    field_samples: dict[str, Any],
    target_fps: float = 30.0,
    update_rate_step: int = 1,
    max_distance_m: Optional[float] = None,
    workers: Optional[int] = None,
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
    progress_cb: Optional[Callable] = None,
    cancel_event: Optional[Any] = None,
    active_process_holder: Optional[dict] = None,
    encoder: str = "nv",
    gpu: int = 0,
    resolution_name: str = "source",
    video_bitrate: str = "",
    rotation_degrees: int = 0,
    container_rotation: int = 0,
    overlay_w: int = 1920,
    overlay_h: int = 1080,
    render_w: int = 1920,
    render_h: int = 1080,
) -> int:
    """
    Producer-Consumer pipeline:
    - Producer: ProcessPoolExecutor renders frames in parallel -> (index, bytes)
    - Consumer: main thread receives, sorts by index, pipes to FFmpeg
    """
    # Pobierz cut_regions z layoutu (przekazane przez kontroler)
    cut_regions = layout.get("cut_regions", [])

    generation_fps = target_fps / update_rate_step
    total_overlay_frames = max(1, math.ceil(duration_s * generation_fps))

    effective_rotation = container_rotation if container_rotation != 0 else rotation_degrees
    init_worker(
        overlay_w, overlay_h, font_path, layout, field_samples, max_distance_m,
        iso_samples, exposure_samples, temperature_samples,
        gpx_speed_samples, gpx_track_samples, gpx_alt_samples,
        gpx_power_samples, gpx_atemp_samples, gpx_hr_samples, gpx_cad_samples,
        fit_data,
        gps_track,
        start_dt_utc, tz_offset_hours,
        speed_samples, track_samples, alt_samples,
        target_fps, update_rate_step, total_overlay_frames,
        cut_regions=cut_regions,
        effective_rotation=effective_rotation,
    )

    if cancel_event is not None and cancel_event.is_set():
        return 0

    # Build FFmpeg input args
    hwaccel = detect_gpu_decoder(encoder)
    input_args: list[str] = []
    audio_input_args: list[str] = []
    if hwaccel:
        input_args.extend(["-hwaccel", hwaccel])
    if isinstance(input_files, list) and len(input_files) > 1:
        concat_txt = Path(output_file).parent / "render_concat_list.txt"
        with open(concat_txt, "w", encoding="utf-8") as f:
            for p in input_files:
                escaped_p = str(p.absolute()).replace("'", "'\\''")
                f.write(f"file '{escaped_p}'\n")
        input_args.extend(["-f", "concat", "-safe", "0", "-i", str(concat_txt)])
        audio_input_args.extend(["-f", "concat", "-safe", "0", "-i", str(concat_txt)])
    else:
        input_file = input_files[0] if isinstance(input_files, list) else input_files
        auto_rot = "-noautorotate" if container_rotation != 0 else "-autorotate"
        input_args.extend([auto_rot, "-i", str(input_file)])
        audio_input_args.extend(["-i", str(input_file)])

    cmd, filter_complex = _build_stream_ffmpeg_cmd(
        ffmpeg_exe, input_args, output_file,
        overlay_w, overlay_h, generation_fps,
        encoder, gpu, video_bitrate,
        render_w, render_h, resolution_name,
        container_rotation, rotation_degrees,
        hwaccel=hwaccel,
        cut_regions=cut_regions,
        audio_input_args=audio_input_args,
    )

    print("FFmpeg streaming cmd:", " ".join(map(str, cmd)), flush=True)
    print(
        f"[STREAM] overlay={overlay_w}x{overlay_h}  render={render_w}x{render_h}  "
        f"gen_fps={generation_fps}  frames={total_overlay_frames}",
        flush=True,
    )
    print(f"[STREAM] filter: {filter_complex}", flush=True)

    # Start FFmpeg
    startupinfo = None
    if os.name == "nt":
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW

    process = subprocess.Popen(
        cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT, universal_newlines=True,
        startupinfo=startupinfo,
    )
    if active_process_holder is not None:
        active_process_holder["process"] = process

    # ── Async stdout reader thread (prevents FFmpeg stdout buffer deadlock) ──
    stdout_lines: list[str] = []

    def _stdout_reader() -> None:
        try:
            for line in process.stdout:
                stdout_lines.append(line.strip())
        except Exception:
            pass

    stdout_t = threading.Thread(target=_stdout_reader, daemon=True)
    stdout_t.start()

    start_time = time.time()
    total_piped = 0
    workers = workers or max(1, (os.cpu_count() or 1) - 1)
    n_workers = min(workers, total_overlay_frames)

    # Frame size in bytes: RGBA = 4 bytes per pixel
    frame_size = overlay_w * overlay_h * 4

    # ── Async pipe writer (background thread) ───────────────────────────
    pipe_queue: queue.Queue = queue.Queue(maxsize=max(8, n_workers * 2))
    pipe_done = threading.Event()
    writer_t = threading.Thread(
        target=_pipe_writer_thread,
        args=(pipe_queue, process.stdin.buffer, pipe_done),
        daemon=True,
    )
    writer_t.start()

    shm_pool: SharedFramePool | None = None

    try:
        if n_workers <= 1:
            # Single worker — no IPC, direct rendering
            for i in range(total_overlay_frames):
                if cancel_event is not None and cancel_event.is_set():
                    break
                _, raw_bytes = render_frame_bytes_job((i,))
                pipe_queue.put(raw_bytes)
                total_piped += 1
                if total_piped % 50 == 0 or total_piped == total_overlay_frames:
                    _report_stream_progress(total_piped, total_overlay_frames, start_time, progress_cb)
        else:
            from concurrent.futures import wait, FIRST_COMPLETED

            # ── Shared Memory pool ──────────────────────────────────────
            # Number of SHM slots: enough to keep workers busy + reorder buffer
            MAX_IN_FLIGHT = max(4, n_workers * 2)
            n_shm_slots = MAX_IN_FLIGHT
            shm_pool = SharedFramePool(n_shm_slots, frame_size)
            shm_names = shm_pool.shm_names()

            init_args = (
                overlay_w, overlay_h, font_path, layout, field_samples, max_distance_m,
                iso_samples, exposure_samples, temperature_samples,
                gpx_speed_samples, gpx_track_samples, gpx_alt_samples,
                gpx_power_samples, gpx_atemp_samples, gpx_hr_samples, gpx_cad_samples,
                fit_data,
                gps_track,
                start_dt_utc, tz_offset_hours,
                speed_samples, track_samples, alt_samples,
                target_fps, update_rate_step, total_overlay_frames,
                cut_regions, effective_rotation,
            )

            print(
                f"[STREAM] SHM pool: {n_shm_slots} slots × {frame_size / 1024 / 1024:.1f} MB = "
                f"{n_shm_slots * frame_size / 1024 / 1024:.0f} MB total | "
                f"workers={n_workers} | MAX_IN_FLIGHT={MAX_IN_FLIGHT}",
                flush=True,
            )

            with ProcessPoolExecutor(
                max_workers=n_workers,
                initializer=_init_worker_with_shm,
                initargs=(shm_names, frame_size, *init_args),
            ) as ex:
                pending: set = set()
                reorder_buf: dict[int, int] = {}  # frame_idx -> shm_slot
                next_idx = 0
                submitted = 0

                # Fill initial window — acquire SHM slots and submit jobs
                for _ in range(min(MAX_IN_FLIGHT, total_overlay_frames)):
                    slot = shm_pool.acquire(timeout=30.0)
                    pending.add(ex.submit(render_frame_shm_job, (submitted, slot)))
                    submitted += 1

                while pending and not (
                    cancel_event is not None and cancel_event.is_set()
                ):
                    done, pending = wait(pending, return_when=FIRST_COMPLETED,
                                         timeout=0.1)
                    for fut in done:
                        idx, slot = fut.result()
                        reorder_buf[idx] = slot

                    # Drain consecutive frames to pipe writer queue
                    while next_idx in reorder_buf:
                        slot = reorder_buf.pop(next_idx)
                        frame_bytes = shm_pool.read(slot)
                        shm_pool.release(slot)
                        pipe_queue.put(frame_bytes)
                        total_piped += 1
                        next_idx += 1
                        if total_piped % 50 == 0 or total_piped == total_overlay_frames:
                            _report_stream_progress(
                                total_piped, total_overlay_frames,
                                start_time, progress_cb,
                            )

                    # Aggressive top-up: fill ALL available slots in the window
                    while (
                        submitted < total_overlay_frames
                        and len(pending) + len(reorder_buf) < MAX_IN_FLIGHT
                    ):
                        slot = shm_pool.acquire(timeout=30.0)
                        pending.add(
                            ex.submit(render_frame_shm_job, (submitted, slot))
                        )
                        submitted += 1

                if cancel_event is not None and cancel_event.is_set():
                    for f in pending:
                        f.cancel()
                    ex.shutdown(wait=False, cancel_futures=True)

                # Drain final reorder buffer
                while next_idx in reorder_buf:
                    slot = reorder_buf.pop(next_idx)
                    frame_bytes = shm_pool.read(slot)
                    shm_pool.release(slot)
                    pipe_queue.put(frame_bytes)
                    total_piped += 1
                    next_idx += 1
                    _report_stream_progress(
                        total_piped, total_overlay_frames,
                        start_time, progress_cb,
                    )

        # Signal pipe writer to finish and close stdin
        pipe_done.set()
        pipe_queue.put(None)  # sentinel
        writer_t.join(timeout=30.0)
        try:
            process.stdin.close()
        except Exception:
            pass
    except BrokenPipeError:
        print("[STREAM] FFmpeg pipe closed unexpectedly.", flush=True)
    except Exception as e:
        print(f"[STREAM] Error: {e}", flush=True)
        import traceback
        traceback.print_exc()
        pipe_done.set()
        pipe_queue.put(None)
        try:
            process.terminate()
        except Exception:
            pass
        raise
    finally:
        # Always clean up SHM pool
        if shm_pool is not None:
            shm_pool.close()

    stdout_t.join(timeout=10.0)
    process.wait()

    if active_process_holder is not None:
        active_process_holder["process"] = None

    rc = process.returncode
    if rc != 0 and not (cancel_event is not None and cancel_event.is_set()):
        extra = "\n".join(stdout_lines).strip()
        raise RuntimeError(f"FFmpeg failed with exit code {rc}\n{extra}")

    if isinstance(input_files, list) and len(input_files) > 1:
        concat_txt = Path(output_file).parent / "render_concat_list.txt"
        if concat_txt.exists():
            concat_txt.unlink()

    return total_piped


# ── Progress reporting ──────────────────────────────────────────────────────


def _report_stream_progress(
    done: int, total: int, start_time: float, progress_cb: Optional[Callable]
) -> None:
    """Report streaming progress."""
    elapsed = time.time() - start_time
    m, s = divmod(int(elapsed), 60)
    h, m = divmod(m, 60)
    fps = done / elapsed if elapsed > 0 else 0
    stats = f"Stream: {done}/{total} | fps: {fps:.1f} | elapse: {h:02d}:{m:02d}:{s:02d}"
    if progress_cb:
        progress_cb(done, stats)


# ── FFmpeg progress runner ──────────────────────────────────────────────────


def run_ffmpeg_with_progress(
    cmd: list[str],
    total_frames: int,
    progress_cb: Callable,
    msg_prefix: str,
    cancel_event: Optional[Any] = None,
    active_process_holder: Optional[dict] = None,
) -> None:
    """Run ffmpeg and parse progress output."""
    cmd.extend(["-progress", "pipe:1", "-nostats", "-loglevel", "error"])
    startupinfo = None
    if os.name == "nt":
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    process = subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        universal_newlines=True, startupinfo=startupinfo,
    )
    if active_process_holder is not None:
        active_process_holder["process"] = process

    frame, fps, out_time, speed = 0, "0", "00:00:00", "0x"
    start_time = time.time()
    other_output: list[str] = []

    for line in process.stdout:
        if cancel_event is not None and cancel_event.is_set():
            try:
                process.terminate()
            except Exception:
                pass
            break
        key, _, val = line.partition("=")
        key, val = key.strip(), val.strip()
        if "=" not in line:
            other_output.append(line.strip())
            continue
        if key == "frame":
            try:
                frame = min(int(val), total_frames)
            except Exception:
                pass
        elif key == "fps":
            fps = val
        elif key == "out_time":
            out_time = val.split(".")[0]
        elif key == "speed":
            speed = val
        elif key == "progress":
            elapsed = int(time.time() - start_time)
            m, s = divmod(elapsed, 60)
            h, m = divmod(m, 60)
            stats = (
                f"{msg_prefix}: {frame}/{total_frames} | fps: {fps} | "
                f"speed: {speed} | time: {out_time} | elapse: {h:02d}:{m:02d}:{s:02d}"
            )
            if progress_cb:
                progress_cb(frame, stats)
    process.wait()
    rc = process.returncode
    if rc != 0:
        extra = "\n".join(other_output).strip()
        raise RuntimeError(f"FFmpeg process failed with exit code {rc}\n{extra}")
    if active_process_holder is not None:
        active_process_holder["process"] = None


# ── Helpers ─────────────────────────────────────────────────────────────────


def scale_filter_for_resolution(resolution_name: str) -> str:
    """Return an ffmpeg scale filter string for the given resolution name."""
    target = RESOLUTION_MAP.get(resolution_name)
    if not target:
        return "[0:v]null[base]"
    w, h = target
    return f"[0:v]scale={w}:{h}:flags=lanczos[base]"


def append_bitrate_args(cmd: list[str], encoder: str, video_bitrate: str) -> list[str]:
    """Append bitrate arguments to an ffmpeg command."""
    if not video_bitrate:
        return cmd
    if encoder in ("nv", "amd"):
        cmd.extend(["-b:v", video_bitrate, "-maxrate", video_bitrate])
        bufsize = video_bitrate
        try:
            if video_bitrate.lower().endswith("m"):
                bufsize = f"{float(video_bitrate[:-1]) * 2:g}M"
            elif video_bitrate.lower().endswith("k"):
                bufsize = f"{float(video_bitrate[:-1]) * 2:g}k"
        except Exception:
            pass
        cmd.extend(["-bufsize", bufsize])
    else:
        cmd.extend(["-b:v", video_bitrate])
    return cmd


# ── Apply overlay video (second pass) ───────────────────────────────────────


def apply_overlay_video(
    ffmpeg_exe: str,
    input_files: list,
    overlay_video: str,
    output_file: str,
    encoder: str,
    gpu: int,
    target_fps: float,
    resolution_name: str = "source",
    video_bitrate: str = "",
    rotation_degrees: int = 0,
    container_rotation: int = 0,
    total_frames: Optional[int] = None,
    progress_cb: Optional[Callable] = None,
    cancel_event: Optional[Any] = None,
    active_process_holder: Optional[dict] = None,
) -> None:
    """Apply a pre-rendered overlay video onto the source video."""
    base_chain = scale_filter_for_resolution(resolution_name)

    hwaccel = detect_gpu_decoder(encoder)

    # Hardware acceleration works natively with rotation metadata in container
    if hwaccel == "cuda":
        ov_op = "overlay_cuda"
        ov_fps = f"[1:v]fps={target_fps},format=rgba,hwupload_cuda"
    else:
        ov_op = "overlay"
        ov_fps = f"[1:v]fps={target_fps}"

    ov_chain = f"{ov_fps}[ov]"

    input_args: list[str] = []
    if hwaccel:
        input_args.extend(["-hwaccel", hwaccel])
        if hwaccel == "qsv":
            input_args.extend(["-hwaccel_output_format", "nv12"])
    if isinstance(input_files, list) and len(input_files) > 1:
        concat_txt = Path(output_file).parent / "render_concat_list.txt"
        with open(concat_txt, "w", encoding="utf-8") as f:
            for p in input_files:
                escaped_p = str(p.absolute()).replace("'", "'\\''")
                f.write(f"file '{escaped_p}'\n")
        input_args.extend(["-f", "concat", "-safe", "0", "-i", str(concat_txt)])
    else:
        input_file = input_files[0] if isinstance(input_files, list) else input_files
        auto_rot = "-noautorotate" if container_rotation != 0 else "-autorotate"
        input_args.extend([auto_rot, "-i", str(input_file)])

    if rotation_degrees == 180:
        filter_complex = (
            f"{base_chain};{ov_chain};"
            f"[base][ov]{ov_op}=0:0:shortest=1[vtemp];"
            f"[vtemp]vflip,hflip[vout]"
        )
    elif rotation_degrees == 90:
        filter_complex = (
            f"{base_chain};{ov_chain};"
            f"[base][ov]{ov_op}=0:0:shortest=1[vtemp];"
            f"[vtemp]transpose=1[vout]"
        )
    elif rotation_degrees == 270:
        filter_complex = (
            f"{base_chain};{ov_chain};"
            f"[base][ov]{ov_op}=0:0:shortest=1[vtemp];"
            f"[vtemp]transpose=2[vout]"
        )
    else:
        filter_complex = (
            f"{base_chain};{ov_chain};"
            f"[base][ov]{ov_op}=0:0:shortest=1[vout]"
        )

    effective_rotation = container_rotation if container_rotation != 0 else (rotation_degrees if rotation_degrees != 0 else 0)
    cmd: list[str] = [
        ffmpeg_exe, "-y",
        *input_args,
        "-i", str(overlay_video),
        "-filter_complex", filter_complex,
        "-map", "[vout]", "-map", "0:a?",
        "-map_metadata", "-1", "-metadata:s:v:0", f"rotate={effective_rotation}",
    ]

    try:
        print("FFmpeg final command:", shlex.join(cmd), flush=True)
    except Exception:
        print("FFmpeg final command:", " ".join(map(str, cmd)), flush=True)

    if encoder == "nv":
        cmd.extend([
            "-c:v", "hevc_nvenc", "-preset", "p1", "-tune", "hq", "-rc", "vbr",
            "-cq", "24", "-pix_fmt", "yuv420p", "-gpu", str(gpu), "-c:a", "copy",
        ])
    elif encoder == "amd":
        amf_encoder = "hevc_amf" if _test_encoder("hevc_amf") else "h264_amf"
        cmd.extend([
            "-c:v", amf_encoder, "-usage", "transcoding", "-quality", "speed",
            "-rc", "cbr", "-pix_fmt", "nv12", "-c:a", "copy",
        ])
    elif encoder == "intel":
        cmd.extend([
            "-c:v", "hevc_qsv", "-preset", "veryfast",
            "-global_quality", "24", "-look_ahead", "0",
            "-async_depth", "4", "-pix_fmt", "nv12", "-c:a", "copy",
        ])
    else:
        cmd.extend([
            "-c:v", "libx265", "-preset", "medium", "-crf", "24",
            "-pix_fmt", "yuv420p", "-c:a", "copy",
        ])

    cmd = append_bitrate_args(cmd, encoder, video_bitrate)
    cmd.append(str(output_file))

    if progress_cb and total_frames:
        run_ffmpeg_with_progress(
            cmd, total_frames, progress_cb, "Render",
            cancel_event=cancel_event, active_process_holder=active_process_holder,
        )
    else:
        if cancel_event is not None and cancel_event.is_set():
            return
        p = subprocess.run(cmd)
        if p.returncode != 0:
            raise RuntimeError(f"Command failed with exit code {p.returncode}")

    if isinstance(input_files, list) and len(input_files) > 1:
        concat_txt = Path(output_file).parent / "render_concat_list.txt"
        if concat_txt.exists():
            concat_txt.unlink()
