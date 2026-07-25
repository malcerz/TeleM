"""FFmpeg overlay rendering and encoding pipeline.

Handles building ffmpeg commands, rendering overlay frames via multiprocessing,
streaming frames directly to ffmpeg via pipe (producer-consumer), and applying
pre-rendered overlay videos.
"""

from __future__ import annotations

import io
import math
import os
import shlex
import subprocess
import time
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime, timedelta
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


def detect_gpu_decoder() -> str | None:
    """Return the best ``-hwaccel`` flag for this system, or ``None`` for CPU.

    Checks NVIDIA (nvidia-smi), then queries ffmpeg -hwaccels for available
    hardware accelerators and validates each candidate with a short test.
    Result is cached in ``_GPU_DECODER_CACHE``.
    """
    global _GPU_DECODER_CACHE
    if _GPU_DECODER_CACHE is not False:
        return _GPU_DECODER_CACHE  # type: ignore[return-value]

    _GPU_DECODER_CACHE = None  # default: CPU only

    # 1) NVIDIA CUDA – quick check via nvidia-smi
    try:
        r = subprocess.run(
            ["nvidia-smi"], capture_output=True, timeout=5,
            **({} if os.name != "nt" else {"startupinfo": _nt_startupinfo()}),
        )
        if r.returncode == 0 and _test_hwaccel("cuda"):
            _GPU_DECODER_CACHE = "cuda"
            return "cuda"
    except Exception:
        pass

    # 2) Probe available hwaccels and test each in priority order
    try:
        r = subprocess.run(
            ["ffmpeg", "-hide_banner", "-hwaccels"],
            capture_output=True, text=True, timeout=5,
            **({} if os.name != "nt" else {"startupinfo": _nt_startupinfo()}),
        )
        if r.returncode == 0:
            accels = r.stdout.lower()
            # Prefer d3d11va on Windows (AMD + Intel), qsv on Intel, vaapi on Linux
            for hw in ("cuda", "d3d11va", "qsv", "vaapi", "vulkan"):
                if hw in accels and _test_hwaccel(hw):
                    _GPU_DECODER_CACHE = hw
                    return hw
    except Exception:
        pass

    return None


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
            # Prefer NVIDIA NVENC, then Intel QSV
            if "hevc_nvenc" in encoders and _test_encoder("hevc_nvenc"):
                # Don't overwrite _GPU_DECODER_CACHE – it belongs to the decoder
                return "nv"
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
    )
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
) -> tuple[list[str], str]:
    """Build the ffmpeg command for the streaming pipeline.

    When *hwaccel* is ``"cuda"``, the GPU ``overlay_cuda`` filter is used
    so that the compositing itself runs on the GPU.  When no rotation is
    needed the composited frame stays in GPU memory all the way to NVENC.
    Rotation filters (vflip/hflip/transpose) are CPU-only, so a single
    ``hwdownload`` is inserted *after* the GPU overlay – before the
    rotation step – rather than downloading every raw video frame first.
    """
    hwaccel_cuda = bool(hwaccel == "cuda")
    needs_rotation = bool(
        rotation_degrees in (90, 180, 270) or container_rotation == 180
    )
    use_gpu_overlay = hwaccel_cuda or (target_res and encoder == "nv")
    target_res = RESOLUTION_MAP.get(resolution_name)

    # ── Base filter (video scaling) ─────────────────────────────────────
    if target_res and encoder == "nv":
        # GPU scaling
        base_filter = (
            f"[0:v]hwupload_cuda,scale_cuda={render_w}:{render_h}[base]"
        )
    elif target_res:
        base_filter = f"[0:v]scale={render_w}:{render_h}:flags=lanczos[base]"
    elif hwaccel_cuda:
        base_filter = "[0:v]null[base]"               # stay on GPU
    else:
        base_filter = "[0:v]null[base]"

    # ── Overlay stream & operator ───────────────────────────────────────
    if hwaccel_cuda:
        ov_input = "[1:v]setpts=PTS-STARTPTS,format=rgba,hwupload_cuda[ov]"
        ov_op = "overlay_cuda"
    else:
        ov_input = "[1:v]setpts=PTS-STARTPTS,format=rgba[ov]"
        ov_op = "overlay"

    # ── Rotation suffix (CPU filters – need hwdownload first) ───────────
    if needs_rotation and hwaccel_cuda:
        _rot_dl = "hwdownload,format=nv12,"
    else:
        _rot_dl = ""

    if container_rotation in (90, 270):
        filter_complex = (
            f"{base_filter};{ov_input};"
            f"[base][ov]{ov_op}=0:0:shortest=1[vout]"
        )
    elif rotation_degrees == 180 or container_rotation == 180:
        filter_complex = (
            f"{base_filter};{ov_input};"
            f"[base][ov]{ov_op}=0:0:shortest=1[vtemp];"
            f"[vtemp]{_rot_dl}vflip,hflip[vout]"
        )
    elif rotation_degrees == 90:
        filter_complex = (
            f"{base_filter};{ov_input};"
            f"[base][ov]{ov_op}=0:0:shortest=1[vtemp];"
            f"[vtemp]{_rot_dl}transpose=1[vout]"
        )
    elif rotation_degrees == 270:
        filter_complex = (
            f"{base_filter};{ov_input};"
            f"[base][ov]{ov_op}=0:0:shortest=1[vtemp];"
            f"[vtemp]{_rot_dl}transpose=2[vout]"
        )
    else:
        filter_complex = (
            f"{base_filter};{ov_input};"
            f"[base][ov]{ov_op}=0:0:shortest=1[vout]"
        )

    cmd: list[str] = [
        ffmpeg_exe, "-y",
        *input_args,
        "-f", "rawvideo", "-pix_fmt", "rgba",
        "-s", f"{overlay_w}x{overlay_h}",
        "-r", str(generation_fps),
        "-i", "pipe:0",
        "-filter_complex", filter_complex,
        "-map", "[vout]", "-map", "0:a?",
        "-map_metadata", "-1", "-metadata:s:v:0", "rotate=0",
    ]

    if encoder == "nv":
        cmd.extend([
            "-c:v", "hevc_nvenc", "-preset", "p1", "-tune", "hq", "-rc", "vbr",
            "-cq", "24", "-pix_fmt", "yuv420p", "-gpu", str(gpu), "-c:a", "copy",
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

    return compose_overlay(
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
    )


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
    generation_fps = target_fps / update_rate_step
    total_overlay_frames = max(1, math.ceil(duration_s * generation_fps))

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
    )

    if cancel_event is not None and cancel_event.is_set():
        return 0

    # Build FFmpeg input args
    hwaccel = detect_gpu_decoder()
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
        input_args.extend(["-autorotate", "-i", str(input_file)])

    cmd, filter_complex = _build_stream_ffmpeg_cmd(
        ffmpeg_exe, input_args, output_file,
        overlay_w, overlay_h, generation_fps,
        encoder, gpu, video_bitrate,
        render_w, render_h, resolution_name,
        container_rotation, rotation_degrees,
        hwaccel=hwaccel,
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

    start_time = time.time()
    total_piped = 0
    jobs = [(i,) for i in range(total_overlay_frames)]
    workers = workers or max(1, (os.cpu_count() or 1) - 1)
    n_workers = min(workers, total_overlay_frames)

    try:
        if n_workers <= 1:
            for i in range(total_overlay_frames):
                if cancel_event is not None and cancel_event.is_set():
                    break
                _, png_bytes = render_frame_bytes_job((i,))
                process.stdin.buffer.write(png_bytes)
                total_piped += 1
                if total_piped % 50 == 0 or total_piped == total_overlay_frames:
                    _report_stream_progress(total_piped, total_overlay_frames, start_time, progress_cb)
        else:
            with ProcessPoolExecutor(
                max_workers=n_workers,
                initializer=init_worker,
                initargs=(
                    overlay_w, overlay_h, font_path, layout, field_samples, max_distance_m,
                    iso_samples, exposure_samples, temperature_samples,
                    gpx_speed_samples, gpx_track_samples, gpx_alt_samples,
                    gpx_power_samples, gpx_atemp_samples, gpx_hr_samples, gpx_cad_samples,
                    fit_data,
                    gps_track,
                    start_dt_utc, tz_offset_hours,
                    speed_samples, track_samples, alt_samples,
                    target_fps, update_rate_step, total_overlay_frames,
                ),
            ) as ex:
                # ex.map() with chunksize = natural sliding window + zero buffer
                chunk = max(1, total_overlay_frames // max(1, n_workers * 4))
                results = ex.map(render_frame_bytes_job, jobs, chunksize=chunk)

                for idx, png_bytes in results:
                    if cancel_event is not None and cancel_event.is_set():
                        try:
                            ex.shutdown(wait=False, cancel_futures=True)
                        except Exception:
                            pass
                        break
                    process.stdin.buffer.write(png_bytes)
                    total_piped += 1
                    if total_piped % 50 == 0 or total_piped == total_overlay_frames:
                        _report_stream_progress(total_piped, total_overlay_frames, start_time, progress_cb)

                if cancel_event is not None and cancel_event.is_set():
                    ex.shutdown(wait=False, cancel_futures=True)

        process.stdin.close()
    except BrokenPipeError:
        print("[STREAM] FFmpeg pipe closed unexpectedly.", flush=True)
    except Exception as e:
        print(f"[STREAM] Error: {e}", flush=True)
        import traceback
        traceback.print_exc()
        try:
            process.terminate()
        except Exception:
            pass
        raise

    remaining: list[str] = []
    for line in process.stdout:
        remaining.append(line.strip())
    process.wait()

    if active_process_holder is not None:
        active_process_holder["process"] = None

    rc = process.returncode
    if rc != 0 and not (cancel_event is not None and cancel_event.is_set()):
        extra = "\n".join(remaining).strip()
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
    if encoder == "nv":
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

    hwaccel = detect_gpu_decoder()
    needs_rotation = bool(
        rotation_degrees in (90, 180, 270) or container_rotation == 180
    )

    # GPU overlay when CUDA is active – download only after overlay if
    # rotation is needed (vflip/hflip/transpose are CPU-side filters).
    if hwaccel == "cuda":
        ov_op = "overlay_cuda"
        ov_fps = f"[1:v]fps={target_fps},format=rgba,hwupload_cuda"
    else:
        ov_op = "overlay"
        ov_fps = f"[1:v]fps={target_fps}"

    # Rotation suffix: hwdownload before CPU-only rotation filters
    _rot_dl = "hwdownload,format=nv12," if needs_rotation and hwaccel == "cuda" else ""
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
        input_args.extend(["-autorotate", "-i", str(input_file)])

    if container_rotation == 180:
        filter_complex = (
            f"{base_chain};{ov_chain};"
            f"[base][ov]{ov_op}=0:0:shortest=1[vout]"
        )
    elif container_rotation in (90, 270):
        filter_complex = (
            f"{base_chain};{ov_chain};"
            f"[base][ov]{ov_op}=0:0:shortest=1[vout]"
        )
    elif rotation_degrees == 180:
        filter_complex = (
            f"{base_chain};{ov_chain};"
            f"[base][ov]{ov_op}=0:0:shortest=1[vtemp];"
            f"[vtemp]{_rot_dl}vflip,hflip[vout]"
        )
    elif rotation_degrees == 90:
        filter_complex = (
            f"{base_chain};{ov_chain};"
            f"[base][ov]{ov_op}=0:0:shortest=1[vtemp];"
            f"[vtemp]{_rot_dl}transpose=1[vout]"
        )
    elif rotation_degrees == 270:
        filter_complex = (
            f"{base_chain};{ov_chain};"
            f"[base][ov]{ov_op}=0:0:shortest=1[vtemp];"
            f"[vtemp]{_rot_dl}transpose=2[vout]"
        )
    else:
        filter_complex = (
            f"{base_chain};{ov_chain};"
            f"[base][ov]{ov_op}=0:0:shortest=1[vout]"
        )

    cmd: list[str] = [
        ffmpeg_exe, "-y",
        *input_args,
        "-i", str(overlay_video),
        "-filter_complex", filter_complex,
        "-map", "[vout]", "-map", "0:a?",
        "-map_metadata", "-1", "-metadata:s:v:0", "rotate=0",
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
