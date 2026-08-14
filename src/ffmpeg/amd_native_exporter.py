"""Production AMD Native D3D11 + AMF Exporter Pipeline for TeleM.

Integrates the native C++ Direct3D 11 GPU VideoProcessor, persistent Python/Pillow RGBA HUD buffer,
and direct AMD AMF hardware encoding inside telem_amd_native.dll.
"""

from __future__ import annotations

import os
import sys
import time
import math
import json
import copy
import statistics
import subprocess
import ctypes
from ctypes import byref, c_void_p, c_uint, c_uint64, c_int, c_double, c_uint8, POINTER
from datetime import datetime, timedelta
import numpy as np
from pathlib import Path
from typing import Any, Callable, Optional

try:
    from PIL import Image
except ImportError:
    Image = None

from src.indicators.compositor import compose_overlay
from src.ffmpeg.worker_cache import init_worker, _resolve_cache_value, WORKER_CACHE


AMD_NATIVE_ABI_VERSION = 4

_AMD_HUD_MODES = {"CPU_REFERENCE": 0, "GPU_HUD": 1}
_AMD_DECODE_MODES = {
    "GPU_HUD_CPU_DECODE_REFERENCE": 0,
    "CPU_DECODE_REFERENCE": 0,
    "GPU_HUD_D3D11VA": 1,
    "D3D11VA": 1,
}


class _HUDDirtyRect(ctypes.Structure):
    _fields_ = [
        ("x", c_uint),
        ("y", c_uint),
        ("width", c_uint),
        ("height", c_uint),
    ]


def _clip_rect(
    rect: tuple[int, int, int, int], width: int, height: int, pad: int = 0
) -> tuple[int, int, int, int] | None:
    x, y, rect_w, rect_h = rect
    left = max(0, int(x) - pad)
    top = max(0, int(y) - pad)
    right = min(width, int(x + rect_w) + pad)
    bottom = min(height, int(y + rect_h) + pad)
    if right <= left or bottom <= top:
        return None
    return left, top, right - left, bottom - top


def _rect_union(
    first: tuple[int, int, int, int], second: tuple[int, int, int, int]
) -> tuple[int, int, int, int]:
    left = min(first[0], second[0])
    top = min(first[1], second[1])
    right = max(first[0] + first[2], second[0] + second[2])
    bottom = max(first[1] + first[3], second[1] + second[3])
    return left, top, right - left, bottom - top


def _rect_intersection_area(
    first: tuple[int, int, int, int], second: tuple[int, int, int, int]
) -> int:
    overlap_w = max(0, min(first[0] + first[2], second[0] + second[2]) - max(first[0], second[0]))
    overlap_h = max(0, min(first[1] + first[3], second[1] + second[3]) - max(first[1], second[1]))
    return overlap_w * overlap_h


def _coalesce_dirty_rects(
    rects: list[tuple[int, int, int, int]],
    max_rects: int,
    merge_area_ratio: float = 1.25,
) -> list[tuple[int, int, int, int]]:
    """Merge overlaps and cheap neighbours without creating a near-full bbox."""
    merged = list(rects)
    changed = True
    while changed:
        changed = False
        for first_index in range(len(merged)):
            for second_index in range(first_index + 1, len(merged)):
                first = merged[first_index]
                second = merged[second_index]
                overlap = _rect_intersection_area(first, second)
                if overlap <= 0:
                    continue
                union = _rect_union(first, second)
                merged.pop(second_index)
                merged.pop(first_index)
                merged.append(union)
                changed = True
                break
            if changed:
                break

    # The limit is a target, not permission to inflate a sparse update into a
    # giant bounding box. Stop if no pair stays within the measured threshold.
    while len(merged) > max_rects:
        best: tuple[float, int, int, tuple[int, int, int, int]] | None = None
        for first_index in range(len(merged)):
            for second_index in range(first_index + 1, len(merged)):
                first = merged[first_index]
                second = merged[second_index]
                union = _rect_union(first, second)
                overlap = _rect_intersection_area(first, second)
                source_area = first[2] * first[3] + second[2] * second[3] - overlap
                ratio = (union[2] * union[3]) / max(1, source_area)
                if ratio <= merge_area_ratio and (best is None or ratio < best[0]):
                    best = (ratio, first_index, second_index, union)
        if best is None:
            break
        _, first_index, second_index, union = best
        merged.pop(second_index)
        merged.pop(first_index)
        merged.append(union)
    return sorted(merged, key=lambda rect: (rect[1], rect[0]))


def _dirty_rects_from_bboxes(
    previous: dict[str, tuple[int, int, int, int]],
    current: dict[str, tuple[int, int, int, int]],
    width: int,
    height: int,
    max_rects: int,
) -> list[tuple[int, int, int, int]]:
    # compose_overlay clears previous indicator bounds with exactly 40 px of
    # padding. Apply the same coverage to both cleared and newly drawn bounds.
    candidates = []
    for bbox in (*previous.values(), *current.values()):
        clipped = _clip_rect(bbox, width, height, pad=40)
        if clipped is not None:
            candidates.append(clipped)
    return _coalesce_dirty_rects(candidates, max_rects=max_rects)


def _env_flag(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _parse_build_info(build_info: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    for item in build_info.split(";"):
        key, separator, value = item.strip().partition("=")
        if separator:
            fields[key.strip()] = value.strip()
    return fields


def _layout_has_hud(layout: dict[str, Any]) -> bool:
    indicators = layout.get("indicators", {})
    if any(
        isinstance(config, dict) and config.get("enabled", True)
        for config in indicators.values()
    ):
        return True
    return any(
        isinstance(config, dict)
        and config.get("enabled", True)
        and bool(str(config.get("text", "")))
        for config in layout.get("custom_texts", [])
    )


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return float(ordered[0])
    position = (len(ordered) - 1) * percentile
    lower = int(math.floor(position))
    upper = int(math.ceil(position))
    if lower == upper:
        return float(ordered[lower])
    weight = position - lower
    return float(ordered[lower] * (1.0 - weight) + ordered[upper] * weight)


def _timing_summary(values: list[float]) -> dict[str, float | int]:
    return {
        "count": len(values),
        "avg_ms": statistics.fmean(values) if values else 0.0,
        "median_ms": statistics.median(values) if values else 0.0,
        "p95_ms": _percentile(values, 0.95),
        "p99_ms": _percentile(values, 0.99),
    }


def _value_summary(values: list[float]) -> dict[str, float | int]:
    return {
        "count": len(values),
        "avg": statistics.fmean(values) if values else 0.0,
        "median": statistics.median(values) if values else 0.0,
        "p95": _percentile(values, 0.95),
        "p99": _percentile(values, 0.99),
    }


def _probe_video_summary(ffmpeg_exe: str, media_path: str) -> dict[str, Any]:
    ffprobe_name = "ffprobe.exe" if os.name == "nt" else "ffprobe"
    ffprobe_path = str(Path(ffmpeg_exe).with_name(ffprobe_name))
    if not os.path.exists(ffprobe_path):
        ffprobe_path = ffprobe_name
    cmd = [
        ffprobe_path, "-v", "error", "-show_entries",
        "format=duration,size:stream=index,codec_type,codec_name,profile,width,height,pix_fmt,avg_frame_rate,duration,nb_frames,sample_rate,channels,color_range,color_space,color_transfer,color_primaries:stream_side_data=rotation",
        "-of", "json", media_path,
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode == 0:
            return json.loads(result.stdout)
    except Exception:
        pass
    return {}


def _stream_frame_count(probe: dict[str, Any], codec_type: str) -> int:
    for stream in probe.get("streams", []):
        if stream.get("codec_type") == codec_type:
            try:
                return int(stream.get("nb_frames") or 0)
            except (TypeError, ValueError):
                return 0
    return 0


def _probe_rotation_degrees(probe: dict[str, Any]) -> int:
    for stream in probe.get("streams", []):
        if stream.get("codec_type") != "video":
            continue
        for side_data in stream.get("side_data_list", []):
            try:
                rotation = int(round(float(side_data.get("rotation", 0))))
            except (TypeError, ValueError):
                continue
            return rotation % 360
    return 0


def _print_timing_table(summaries: dict[str, dict[str, float | int]]) -> None:
    print("\n[AMD NATIVE ETAP 0 TIMINGS]", flush=True)
    print(f"{'Stage':32} {'AVG ms':>10} {'Median':>10} {'P95':>10} {'P99':>10}", flush=True)
    print("-" * 76, flush=True)
    for stage, data in summaries.items():
        print(
            f"{stage:32} {data['avg_ms']:10.3f} {data['median_ms']:10.3f} "
            f"{data['p95_ms']:10.3f} {data['p99_ms']:10.3f}",
            flush=True,
        )

def export_amd_native_d3d11(
    ffmpeg_exe: str,
    input_files: list,
    output_file: str,
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
    target_fps: float = 29.97,
    video_bitrate: str = "",
    codec: str = "hevc_amf",
    quality: str = "speed",
    rc: str = "cqp",
    qp_p: int = 28,
    qp_i: int = 28,
    max_distance_m: Optional[float] = None,
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
    progress_cb: Optional[Callable[[int, str], None]] = None,
    cancel_event: Optional[Any] = None,
    active_process_holder: Optional[dict] = None,
) -> bool:
    """Execute production native AMD D3D11 + AMF video export pipeline via telem_amd_native.dll."""
    # The GUI starts export on a worker thread while its editable layout remains
    # reachable by the UI.  Snapshot it once so rendering and the ETAP 5B
    # dependency plan are immutable for the whole export.
    layout = copy.deepcopy(layout)
    total_frames = max(1, math.ceil(duration_s * target_fps))
    input_file = input_files[0] if isinstance(input_files, list) else input_files
    input_file_str = str(Path(input_file).resolve())
    output_file_str = str(Path(output_file).resolve())
    diagnostics_enabled = _env_flag("AMD_NATIVE_DIAGNOSTICS", False)
    profiling_enabled = diagnostics_enabled or _env_flag("AMD_NATIVE_PROFILING", False)
    overlay_profile_enabled = _env_flag("AMD_OVERLAY_PROFILE", False)
    native_hud_mode = os.environ.get("AMD_NATIVE_HUD_MODE", "GPU_HUD").strip().upper()
    if native_hud_mode not in _AMD_HUD_MODES:
        print(
            "[AMD NATIVE D3D11] ERROR: AMD_NATIVE_HUD_MODE must be "
            "CPU_REFERENCE or GPU_HUD.",
            flush=True,
        )
        return False
    native_decode_mode = os.environ.get(
        "AMD_NATIVE_DECODE_MODE", "GPU_HUD_D3D11VA"
    ).strip().upper()
    if native_decode_mode not in _AMD_DECODE_MODES:
        print(
            "[AMD NATIVE D3D11] ERROR: AMD_NATIVE_DECODE_MODE must be "
            "GPU_HUD_D3D11VA or GPU_HUD_CPU_DECODE_REFERENCE.",
            flush=True,
        )
        return False
    use_d3d11va = _AMD_DECODE_MODES[native_decode_mode] == 1
    hud_upload_mode = os.environ.get("AMD_NATIVE_HUD_UPLOAD_MODE", "DIRTY").strip().upper()
    if hud_upload_mode not in {"FULL", "DIRTY"}:
        print(
            "[AMD NATIVE D3D11] ERROR: AMD_NATIVE_HUD_UPLOAD_MODE must be FULL or DIRTY.",
            flush=True,
        )
        return False
    try:
        dirty_max_rects = int(os.environ.get("AMD_NATIVE_DIRTY_MAX_RECTS", "8"))
    except ValueError:
        dirty_max_rects = 8
    if dirty_max_rects not in {4, 8, 16}:
        print("[AMD NATIVE D3D11] ERROR: AMD_NATIVE_DIRTY_MAX_RECTS must be 4, 8 or 16.", flush=True)
        return False
    hud_enabled = _layout_has_hud(layout)
    legacy_no_hud = not hud_enabled and _env_flag("AMD_NATIVE_LEGACY_NO_HUD", False)
    hud_work_enabled = hud_enabled or legacy_no_hud
    from src.indicators.frame_data import build_active_fit_field_plan

    fit_field_plan = build_active_fit_field_plan(layout, (fit_data or {}).keys())
    print(
        "AMD ETAP 5B FIT discovered: "
        + ", ".join(fit_field_plan["discovered_fit_fields"]),
        flush=True,
    )
    print(
        "AMD ETAP 5B FIT active: "
        + ", ".join(fit_field_plan["active_fit_fields"]),
        flush=True,
    )
    print(
        "AMD ETAP 5B FIT skipped: "
        + ", ".join(fit_field_plan["inactive_fit_fields"]),
        flush=True,
    )
    input_probe = _probe_video_summary(ffmpeg_exe, input_file_str)
    source_frames = _stream_frame_count(input_probe, "video")
    source_rotation = _probe_rotation_degrees(input_probe)

    # 1. Locate and Load telem_amd_native.dll
    repo_root = Path(__file__).resolve().parents[2]
    dll_path = str(
        (repo_root / "native" / "d3d11_amf_pipeline" / "bin" / "telem_amd_native.dll").resolve()
    )
    if not os.path.exists(dll_path):
        print(f"[AMD NATIVE D3D11] ERROR: DLL not found at {dll_path}", flush=True)
        print("AMD_NATIVE_D3D11 = FAIL", flush=True)
        return False

    if hasattr(os, "add_dll_directory"):
        mingw_bin = r"c:\tools\mingw64\bin"
        if os.path.exists(mingw_bin):
            os.add_dll_directory(mingw_bin)

    try:
        native_dll = ctypes.CDLL(dll_path)
    except Exception as e:
        print(f"[AMD NATIVE D3D11] Failed to load DLL {dll_path}: {e}", flush=True)
        print("AMD_NATIVE_D3D11 = FAIL", flush=True)
        return False

    try:
        native_dll.telem_amd_get_abi_version.restype = c_uint
        native_dll.telem_amd_get_abi_version.argtypes = []
        native_dll.telem_amd_get_build_info.restype = ctypes.c_char_p
        native_dll.telem_amd_get_build_info.argtypes = []
        loaded_abi = int(native_dll.telem_amd_get_abi_version())
        build_info_raw = native_dll.telem_amd_get_build_info()
        build_info = build_info_raw.decode("utf-8", errors="replace") if build_info_raw else "missing"
    except (AttributeError, OSError) as exc:
        print(f"[AMD NATIVE D3D11] ERROR: DLL does not expose ETAP 0 ABI: {exc}", flush=True)
        print("[AMD NATIVE D3D11] Native backend rejected; caller may use explicit fallback.", flush=True)
        return False

    if loaded_abi != AMD_NATIVE_ABI_VERSION:
        print(
            f"[AMD NATIVE D3D11] ERROR: ABI mismatch: expected={AMD_NATIVE_ABI_VERSION}, "
            f"loaded={loaded_abi}",
            flush=True,
        )
        print("[AMD NATIVE D3D11] Native backend rejected; caller may use explicit fallback.", flush=True)
        return False

    build_fields = _parse_build_info(build_info)
    build_id = build_fields.get("build_id", "missing")
    embedded_build_time = build_fields.get("build_timestamp", "missing")
    file_build_time = datetime.fromtimestamp(os.path.getmtime(dll_path)).astimezone().isoformat(timespec="seconds")
    print(f"AMD Native DLL path: {dll_path}", flush=True)
    print(f"AMD Native DLL build ID: {build_id}", flush=True)
    print(f"AMD Native DLL build timestamp: {embedded_build_time}", flush=True)
    print(f"AMD Native DLL file timestamp: {file_build_time}", flush=True)
    print(f"AMD Native DLL ABI: {loaded_abi}", flush=True)
    print(f"AMD_NATIVE_DIAGNOSTICS: {'ON' if diagnostics_enabled else 'OFF'}", flush=True)
    print(f"AMD_NATIVE_PROFILING: {'ON' if profiling_enabled else 'OFF'}", flush=True)
    hud_mode = "ON" if hud_enabled else ("OFF (legacy benchmark)" if legacy_no_hud else "OFF (fast path)")
    print(f"AMD Native HUD: {hud_mode}", flush=True)
    print(f"AMD Native HUD compositor: {native_hud_mode}", flush=True)
    print(f"AMD Native video decode: {native_decode_mode}", flush=True)
    print(f"AMD Native source rotation: {source_rotation}", flush=True)
    print(f"AMD Native HUD upload path: {hud_upload_mode}", flush=True)
    if hud_upload_mode == "DIRTY":
        print(f"AMD Native dirty rect target: {dirty_max_rects}", flush=True)

    # Function Signatures
    native_dll.telem_amd_create.restype = c_void_p
    native_dll.telem_amd_create.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p, c_uint, c_uint, c_uint, c_uint]

    native_dll.telem_amd_update_hud.restype = c_int
    native_dll.telem_amd_update_hud.argtypes = [c_void_p, ctypes.c_char_p, c_uint, c_uint, c_uint]

    native_dll.telem_amd_update_hud_regions.restype = c_int
    native_dll.telem_amd_update_hud_regions.argtypes = [
        c_void_p, POINTER(c_uint8), c_uint, c_uint, c_uint,
        POINTER(_HUDDirtyRect), c_uint, c_int,
    ]

    native_dll.telem_amd_update_video_frame.restype = c_int
    native_dll.telem_amd_update_video_frame.argtypes = [c_void_p, ctypes.c_char_p, c_uint, c_uint, c_uint]

    native_dll.telem_amd_process_frame.restype = c_int
    native_dll.telem_amd_process_frame.argtypes = [c_void_p, c_uint, c_int]

    native_dll.telem_amd_dump_checkpoint.restype = c_int
    native_dll.telem_amd_dump_checkpoint.argtypes = [c_void_p, c_uint, ctypes.c_char_p, ctypes.c_wchar_p]

    native_dll.telem_amd_flush.restype = c_int
    native_dll.telem_amd_flush.argtypes = [c_void_p]

    native_dll.telem_amd_close.restype = c_int
    native_dll.telem_amd_close.argtypes = [c_void_p]

    native_dll.telem_amd_get_stats.restype = None
    native_dll.telem_amd_get_stats.argtypes = [c_void_p, POINTER(c_uint64), POINTER(c_uint64), POINTER(c_uint64), POINTER(c_uint64)]

    native_dll.telem_amd_set_diagnostics.restype = c_int
    native_dll.telem_amd_set_diagnostics.argtypes = [c_void_p, c_int]

    native_dll.telem_amd_set_profiling.restype = c_int
    native_dll.telem_amd_set_profiling.argtypes = [c_void_p, c_int]

    native_dll.telem_amd_set_hud_enabled.restype = c_int
    native_dll.telem_amd_set_hud_enabled.argtypes = [c_void_p, c_int]

    native_dll.telem_amd_set_hud_mode.restype = c_int
    native_dll.telem_amd_set_hud_mode.argtypes = [c_void_p, c_int]

    native_dll.telem_amd_set_source_rotation.restype = c_int
    native_dll.telem_amd_set_source_rotation.argtypes = [c_void_p, c_uint]

    native_dll.telem_amd_set_decode_mode.restype = c_int
    native_dll.telem_amd_set_decode_mode.argtypes = [c_void_p, c_int]

    native_dll.telem_amd_read_video_sample.restype = c_int
    native_dll.telem_amd_read_video_sample.argtypes = [
        c_void_p, POINTER(c_uint64), POINTER(ctypes.c_int64), POINTER(ctypes.c_int64),
        POINTER(c_uint), POINTER(c_uint), POINTER(c_uint), POINTER(c_uint),
        POINTER(c_uint), POINTER(c_uint64),
    ]

    native_dll.telem_amd_get_extended_stats.restype = None
    native_dll.telem_amd_get_extended_stats.argtypes = [
        c_void_p,
        POINTER(c_uint64), POINTER(c_uint64), POINTER(c_uint64),
        POINTER(c_uint64), POINTER(c_uint64), POINTER(c_uint64),
    ]

    native_dll.telem_amd_get_last_frame_timings.restype = None
    native_dll.telem_amd_get_last_frame_timings.argtypes = [c_void_p] + [POINTER(c_double)] * 14

    native_dll.telem_amd_get_etap1_stats.restype = None
    native_dll.telem_amd_get_etap1_stats.argtypes = [
        c_void_p, POINTER(c_uint64), POINTER(c_uint64),
    ]

    native_dll.telem_amd_get_etap2_stats.restype = None
    native_dll.telem_amd_get_etap2_stats.argtypes = [
        c_void_p, POINTER(c_uint64), POINTER(c_uint64), POINTER(c_uint64), POINTER(c_int),
    ]

    native_dll.telem_amd_get_etap3_stats.restype = None
    native_dll.telem_amd_get_etap3_stats.argtypes = [
        c_void_p, POINTER(c_uint64), POINTER(c_uint64),
    ]

    native_dll.telem_amd_get_etap4_stats.restype = None
    native_dll.telem_amd_get_etap4_stats.argtypes = [
        c_void_p,
        *([POINTER(c_uint64)] * 9),
        POINTER(c_int), POINTER(c_int), POINTER(c_uint),
    ]

    # 2. Log Telemetry Channel Availability
    gpmf_count = len(speed_samples) if speed_samples else 0
    fit_speed_samples = (fit_data or {}).get("speed", [])
    fit_count = len(fit_speed_samples) if fit_speed_samples else 0
    gpx_count = len(gpx_speed_samples) if gpx_speed_samples else 0

    print(f"\n[TELEMETRY CHANNELS LOG]", flush=True)
    print(f"  GPMF records count: {gpmf_count}", flush=True)
    print(f"  FIT records count:  {fit_count}", flush=True)
    print(f"  GPX records count:  {gpx_count}", flush=True)

    base_dt = start_dt_utc or datetime.now()

    # 3. Initialize HUD/telemetry worker cache only when this export will
    # actually generate HUD frames (or when explicitly benchmarking ETAP 0).
    if hud_work_enabled:
        init_worker(
            video_width=video_width,
            video_height=video_height,
            font_path=font_path,
            layout=layout,
            field_samples=field_samples,
            max_distance_m=max_distance_m,
            iso_samples=iso_samples,
            exposure_samples=exposure_samples,
            temperature_samples=temperature_samples,
            gpx_speed_samples=gpx_speed_samples,
            gpx_track_samples=gpx_track_samples,
            gpx_alt_samples=gpx_alt_samples,
            gpx_power_samples=gpx_power_samples,
            gpx_atemp_samples=gpx_atemp_samples,
            gpx_hr_samples=gpx_hr_samples,
            gpx_cad_samples=gpx_cad_samples,
            fit_data=fit_data,
            gps_track=gps_track,
            start_dt_utc=base_dt,
            tz_offset_hours=tz_offset_hours,
            speed_samples=speed_samples,
            track_samples=track_samples,
            alt_samples=alt_samples,
            target_fps=target_fps,
            update_rate_step=1,
            total_overlay_frames=total_frames,
        )

    fps_num = int(round(target_fps * 1000))
    fps_den = 1000

    print("[AMD NATIVE D3D11] Initializing telem_amd_native context...", flush=True)
    h_context = native_dll.telem_amd_create(
        input_file_str,
        output_file_str,
        video_width,
        video_height,
        fps_num,
        fps_den
    )

    if not h_context:
        print("[AMD NATIVE D3D11] ERROR: telem_amd_create returned NULL!", flush=True)
        print("AMD_NATIVE_D3D11 = FAIL", flush=True)
        return False

    if not native_dll.telem_amd_set_diagnostics(h_context, 1 if diagnostics_enabled else 0):
        print("[AMD NATIVE D3D11] ERROR: failed to configure diagnostic mode.", flush=True)
        native_dll.telem_amd_close(h_context)
        return False

    if not native_dll.telem_amd_set_profiling(h_context, 1 if profiling_enabled else 0):
        print("[AMD NATIVE D3D11] ERROR: failed to configure profiling mode.", flush=True)
        native_dll.telem_amd_close(h_context)
        return False

    if not native_dll.telem_amd_set_hud_enabled(h_context, 1 if hud_work_enabled else 0):
        print("[AMD NATIVE D3D11] ERROR: failed to configure HUD mode.", flush=True)
        native_dll.telem_amd_close(h_context)
        return False

    if not native_dll.telem_amd_set_hud_mode(h_context, _AMD_HUD_MODES[native_hud_mode]):
        print("[AMD NATIVE D3D11] ERROR: failed to configure HUD compositor.", flush=True)
        native_dll.telem_amd_close(h_context)
        return False

    if not native_dll.telem_amd_set_source_rotation(h_context, source_rotation):
        print("[AMD NATIVE D3D11] ERROR: failed to configure source rotation.", flush=True)
        native_dll.telem_amd_close(h_context)
        return False

    if not native_dll.telem_amd_set_decode_mode(
        h_context, _AMD_DECODE_MODES[native_decode_mode]
    ):
        print(
            f"[AMD NATIVE D3D11] ERROR: decode mode {native_decode_mode} unavailable; "
            "no implicit per-frame fallback is allowed.",
            flush=True,
        )
        native_dll.telem_amd_close(h_context)
        return False

    base_dt = start_dt_utc or datetime.now()
    start_time = time.time()
    progress_interval = max(1, min(10, total_frames // 100))

    from src.indicators.frame_data import prepare_overlay_frame_data
    from src.indicators.profiling import get_overlay_profiler

    overlay_profiler = get_overlay_profiler()
    fit_resolve_stats: dict[str, Any] | None = (
        {"calls": 0, "per_field": {}} if overlay_profile_enabled else None
    )
    print(
        f"AMD_OVERLAY_PROFILE: {'ON' if overlay_profile_enabled else 'OFF'}",
        flush=True,
    )

    timing_samples: dict[str, list[float]] = {
        "Decode/pipe wait": [],
        "MF ReadSample/decode availability": [],
        "MF decoder surface acquisition": [],
        "Decoder surface GPU copy": [],
        "Telemetry/frame_data": [],
        "compose_overlay": [],
        "PIL tobytes": [],
        "PIL/buffer preparation": [],
        "Python->native bridge": [],
        "update_hud": [],
        "Native HUD CPU copy": [],
        "HUD texture upload": [],
        "NV12 staging memcpy": [],
        "BlendRGBAToNV12": [],
        "CopyResource submission": [],
        "VideoProcessor CPU submit": [],
        "VideoProcessor GPU completion": [],
        "GPU wait/synchronization": [],
        "AMF submit/backpressure": [],
        "AMF QueryOutput": [],
        "Packet write": [],
        "Audio mux": [],
    }
    decoded_frames_python = 0
    hud_frames = 0
    successful_hud_updates = 0
    successful_video_updates = 0
    hud_frame_bytes = video_width * video_height * 4
    hud_backing = (c_uint8 * hud_frame_bytes)() if hud_work_enabled and native_hud_mode == "GPU_HUD" else None
    hud_backing_view = (
        np.ctypeslib.as_array(hud_backing).reshape((video_height, video_width, 4))
        if hud_backing is not None else None
    )
    hud_backing_address = ctypes.addressof(hud_backing) if hud_backing is not None else 0
    hud_pointer_observations: list[int] = []
    dirty_rect_counts: list[int] = []
    requested_upload_bytes: list[int] = []
    pillow_intermediate_bytes: list[int] = []
    python_persistent_copy_bytes: list[int] = []
    previous_bboxes: dict[str, tuple[int, int, int, int]] = {}
    last_hud_call_ms = 0.0
    sample_timestamps: dict[int, dict[str, float | int]] = {}

    # CPU reference keeps the ETAP 3 FFmpeg rawvideo pipe. D3D11VA never
    # starts a video decoder subprocess; samples come from MF as GPU surfaces.
    cmd_decode: list[str] | None = None
    frame_size = video_width * video_height * 3 // 2
    end_to_end_start = time.perf_counter()
    proc_dec: subprocess.Popen | None = None
    if not use_d3d11va:
        cmd_decode = [
            ffmpeg_exe, "-y",
            "-i", input_file_str,
            "-vf", f"scale={video_width}:{video_height},format=nv12",
            "-f", "rawvideo",
            "-pix_fmt", "nv12",
            "pipe:1"
        ]
        try:
            proc_dec = subprocess.Popen(
                cmd_decode,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL
            )
        except Exception as e:
            print(f"[AMD NATIVE D3D11] ERROR: Failed to launch decoder pipe: {e}", flush=True)
            native_dll.telem_amd_close(h_context)
            return False
    else:
        print("[AMD NATIVE D3D11VA] FFmpeg rawvideo decoder pipe: OFF", flush=True)

    # Main Frame Processing Loop
    frame_idx = 0
    expected_progress_frames = source_frames if use_d3d11va and source_frames else total_frames
    while True:
        # Short validation exports may deliberately request fewer frames than
        # the source contains.  The full production export still terminates on
        # the SourceReader EOS event, so no duration-derived synthetic frame is
        # ever produced.
        if decoded_frames_python >= total_frames:
            break
        if cancel_event is not None and cancel_event.is_set():
            print("[AMD NATIVE D3D11] Export cancelled by user.", flush=True)
            if proc_dec is not None:
                proc_dec.kill()
            native_dll.telem_amd_close(h_context)
            return False

        raw_nv12: bytes | None = None
        sample_time_seconds = frame_idx / target_fps
        if use_d3d11va:
            while True:
                sample_index = c_uint64(0)
                sample_pts = ctypes.c_int64(0)
                sample_duration = ctypes.c_int64(0)
                sample_flags = c_uint(0)
                sample_format = c_uint(0)
                sample_width = c_uint(0)
                sample_height = c_uint(0)
                sample_subresource = c_uint(0)
                sample_texture = c_uint64(0)
                read_status = native_dll.telem_amd_read_video_sample(
                    h_context,
                    byref(sample_index), byref(sample_pts), byref(sample_duration),
                    byref(sample_flags), byref(sample_format), byref(sample_width),
                    byref(sample_height), byref(sample_subresource), byref(sample_texture),
                )
                if read_status == 2:
                    continue
                break
            if read_status == 0:
                break
            if read_status < 0:
                print("[AMD NATIVE D3D11VA] ERROR: native ReadSample failed.", flush=True)
                native_dll.telem_amd_close(h_context)
                return False
            frame_idx = int(sample_index.value)
            sample_time_seconds = sample_pts.value / 10_000_000.0
            decoded_frames_python += 1
            if frame_idx in {0, 30, 300, 600, 900}:
                reference_pts = frame_idx / target_fps
                sample_timestamps[frame_idx] = {
                    "frame_index": frame_idx,
                    "mf_pts_100ns": int(sample_pts.value),
                    "mf_pts_seconds": sample_time_seconds,
                    "cpu_reference_seconds": reference_pts,
                    "delta_ms": (sample_time_seconds - reference_pts) * 1000.0,
                    "duration_100ns": int(sample_duration.value),
                    "dxgi_format": int(sample_format.value),
                    "subresource": int(sample_subresource.value),
                    "texture_pointer": hex(sample_texture.value),
                }
        else:
            if frame_idx >= total_frames:
                break
            assert proc_dec is not None and proc_dec.stdout is not None
            decode_wait_start = time.perf_counter()
            raw_nv12 = proc_dec.stdout.read(frame_size)
            decode_wait_ms = (time.perf_counter() - decode_wait_start) * 1000.0
            if len(raw_nv12) != frame_size:
                break
            timing_samples["Decode/pipe wait"].append(decode_wait_ms)
            decoded_frames_python += 1

        if diagnostics_enabled and raw_nv12 is not None and (frame_idx == 0 or frame_idx == 30):
            y_arr = np.frombuffer(raw_nv12[:video_width * video_height], dtype=np.uint8)
            print(f"[DECODER PIPE] Frame {frame_idx} NV12 Y-channel: min={y_arr.min()}, max={y_arr.max()}, mean={y_arr.mean():.1f}", flush=True)

        if diagnostics_enabled and raw_nv12 is not None and frame_idx == 30:
            # Checkpoint A: raw NV12 from FFmpeg before D3D11 upload
            y_size = video_width * video_height
            y_p = np.frombuffer(raw_nv12[:y_size], dtype=np.uint8).reshape((video_height, video_width))
            uv_p = np.frombuffer(raw_nv12[y_size:], dtype=np.uint8).reshape((video_height // 2, video_width // 2, 2))
            u = np.repeat(np.repeat(uv_p[:, :, 0], 2, axis=0), 2, axis=1).astype(np.float32) - 128.0
            v = np.repeat(np.repeat(uv_p[:, :, 1], 2, axis=0), 2, axis=1).astype(np.float32) - 128.0
            y = y_p.astype(np.float32)
            r = np.clip(y + 1.402 * v, 0, 255).astype(np.uint8)
            g = np.clip(y - 0.344136 * u - 0.714136 * v, 0, 255).astype(np.uint8)
            b = np.clip(y + 1.772 * u, 0, 255).astype(np.uint8)
            rgb = np.dstack([r, g, b])
            if Image:
                Image.fromarray(rgb, "RGB").save("A_base_cpu_nv12.png")
                print("[CHECKPOINT] Saved A_base_cpu_nv12.png", flush=True)

        if hud_work_enabled:
            curr_dt = base_dt + timedelta(seconds=sample_time_seconds)
            chart_data = WORKER_CACHE.get("_precomputed_chart_data", {})

            overlay_profiler.start_frame(frame_idx, video_width, video_height)

            telemetry_start = time.perf_counter()
            frame_kwargs = prepare_overlay_frame_data(
                layout=layout,
                target_dt=curr_dt,
                start_dt_utc=base_dt,
                tz_offset_hours=tz_offset_hours,
                speed_samples=speed_samples,
                track_samples=track_samples,
                alt_samples=alt_samples,
                iso_samples=iso_samples,
                exposure_samples=exposure_samples,
                temperature_samples=temperature_samples,
                total_frames=total_frames,
                current_index=frame_idx,
                chart_data=chart_data,
                resolve_cache_value=_resolve_cache_value,
                gpx_speed_samples=gpx_speed_samples,
                gpx_track_samples=gpx_track_samples,
                gpx_alt_samples=gpx_alt_samples,
                gpx_power_samples=gpx_power_samples,
                gpx_atemp_samples=gpx_atemp_samples,
                gpx_hr_samples=gpx_hr_samples,
                gpx_cad_samples=gpx_cad_samples,
                fit_data=fit_data,
                gps_track=gps_track,
                _range_cache=WORKER_CACHE.get("_prep_cache"),
                fit_field_plan=fit_field_plan,
                resolve_stats=fit_resolve_stats,
            )
            telemetry_elapsed_ms = (time.perf_counter() - telemetry_start) * 1000.0
            timing_samples["Telemetry/frame_data"].append(telemetry_elapsed_ms)
            overlay_profiler.record(
                "telemetry.prepare_overlay_frame_data", telemetry_elapsed_ms
            )

            if frame_idx % 30 == 0:
                print(f"Frame {frame_idx}: HR={frame_kwargs.get('hr_value')}, CAD={frame_kwargs.get('cad_value')}", flush=True)

            _bboxes = {}
            compose_start = time.perf_counter()
            composed_img = compose_overlay(
                canvas_w=video_width,
                canvas_h=video_height,
                layout=layout,
                font_path=font_path,
                _bboxes=_bboxes,
                **frame_kwargs
            )
            compose_elapsed_ms = (time.perf_counter() - compose_start) * 1000.0
            timing_samples["compose_overlay"].append(compose_elapsed_ms)
            overlay_profiler.record("compose.total", compose_elapsed_ms)
            overlay_profiler.finish_frame()
            hud_frames += 1

            if diagnostics_enabled and frame_idx == 30:
                print("\n=== REAL GUI EXPORT TRACE (Frame 30) ===", flush=True)
                composed_img.save("01_python_hud.png")

            if native_hud_mode == "CPU_REFERENCE":
                tobytes_start = time.perf_counter()
                rgba_bytes = composed_img.tobytes("raw", "RGBA")
                timing_samples["PIL tobytes"].append((time.perf_counter() - tobytes_start) * 1000.0)
                update_hud_start = time.perf_counter()
                hud_update_ok = native_dll.telem_amd_update_hud(
                    h_context,
                    rgba_bytes,
                    video_width,
                    video_height,
                    video_width * 4
                )
                last_hud_call_ms = (time.perf_counter() - update_hud_start) * 1000.0
            else:
                assert hud_backing is not None and hud_backing_view is not None
                buffer_prep_start = time.perf_counter()
                full_upload = hud_upload_mode == "FULL" or hud_frames == 1
                if full_upload:
                    # Pillow does not expose a supported writable buffer for an
                    # RGBA image. Materialize once into NumPy, then perform one
                    # controlled copy into the stable ctypes backing allocation.
                    image_array = np.asarray(composed_img, dtype=np.uint8)
                    if image_array.shape != hud_backing_view.shape:
                        raise RuntimeError(f"Unexpected Pillow RGBA shape: {image_array.shape}")
                    np.copyto(hud_backing_view, image_array)
                    dirty_rects: list[tuple[int, int, int, int]] = []
                    intermediate_bytes = hud_frame_bytes
                    persistent_copy_bytes = hud_frame_bytes
                    upload_bytes = hud_frame_bytes
                    rect_count = 1
                else:
                    dirty_rects = _dirty_rects_from_bboxes(
                        previous_bboxes, _bboxes,
                        video_width, video_height, dirty_max_rects,
                    )
                    intermediate_bytes = 0
                    persistent_copy_bytes = 0
                    upload_bytes = 0
                    for x, y, rect_w, rect_h in dirty_rects:
                        region = composed_img.crop((x, y, x + rect_w, y + rect_h))
                        region_array = np.asarray(region, dtype=np.uint8)
                        np.copyto(hud_backing_view[y:y + rect_h, x:x + rect_w], region_array)
                        region_bytes = rect_w * rect_h * 4
                        intermediate_bytes += region_bytes
                        persistent_copy_bytes += region_bytes
                        upload_bytes += region_bytes
                    rect_count = len(dirty_rects)
                timing_samples["PIL/buffer preparation"].append(
                    (time.perf_counter() - buffer_prep_start) * 1000.0
                )
                pillow_intermediate_bytes.append(intermediate_bytes)
                python_persistent_copy_bytes.append(persistent_copy_bytes)
                requested_upload_bytes.append(upload_bytes)
                dirty_rect_counts.append(rect_count)
                previous_bboxes = dict(_bboxes)

                if dirty_rects:
                    native_rects = (_HUDDirtyRect * len(dirty_rects))(
                        *(_HUDDirtyRect(*rect) for rect in dirty_rects)
                    )
                    native_rect_ptr = native_rects
                    native_rect_count = len(dirty_rects)
                else:
                    native_rect_ptr = None
                    native_rect_count = 0
                hud_pointer_observations.append(hud_backing_address)
                if diagnostics_enabled and frame_idx == 30 and Image:
                    Image.fromarray(hud_backing_view, "RGBA").save("02_buffer_sent_to_dll.png")
                    print(
                        "[AMD NATIVE ETAP 3] Pillow pixel pointer: unavailable through "
                        "the supported writable buffer protocol",
                        flush=True,
                    )
                    print(
                        f"[AMD NATIVE ETAP 3] Persistent backing pointer sent to DLL: "
                        f"{hex(hud_backing_address)}",
                        flush=True,
                    )
                update_hud_start = time.perf_counter()
                hud_update_ok = native_dll.telem_amd_update_hud_regions(
                    h_context,
                    hud_backing,
                    video_width,
                    video_height,
                    video_width * 4,
                    native_rect_ptr,
                    native_rect_count,
                    1 if full_upload else 0,
                )
                last_hud_call_ms = (time.perf_counter() - update_hud_start) * 1000.0
            timing_samples["update_hud"].append(last_hud_call_ms)
            if not hud_update_ok:
                print(f"[AMD NATIVE D3D11] ERROR: telem_amd_update_hud failed on frame {frame_idx}", flush=True)
                if proc_dec is not None:
                    proc_dec.kill()
                native_dll.telem_amd_close(h_context)
                return False
            successful_hud_updates += 1

        # CPU reference uploads a raw NV12 frame. D3D11VA already has a GPU
        # decoder surface and must never call this staging path.
        if not use_d3d11va:
            assert raw_nv12 is not None
            video_update_ok = native_dll.telem_amd_update_video_frame(
                h_context,
                raw_nv12,
                video_width,
                video_height,
                video_width
            )
            if not video_update_ok:
                print(f"[AMD NATIVE D3D11] ERROR: telem_amd_update_video_frame failed on frame {frame_idx}", flush=True)
                if proc_dec is not None:
                    proc_dec.kill()
                native_dll.telem_amd_close(h_context)
                return False
            successful_video_updates += 1
        if diagnostics_enabled and not use_d3d11va and frame_idx == 30:
            # Checkpoint B: readback of D3D11 texture after upload, before VP
            native_dll.telem_amd_dump_checkpoint(h_context, 30, b"B_base_d3d11", os.path.abspath("B_base_d3d11.png"))

        # Process frame inside native DLL (VideoProcessor blit -> AMF encode)
        ret = native_dll.telem_amd_process_frame(h_context, frame_idx, 1 if hud_enabled else 0)
        if not ret:
            print(f"[AMD NATIVE D3D11] ERROR: telem_amd_process_frame failed on frame {frame_idx}", flush=True)
            if proc_dec is not None:
                proc_dec.kill()
            native_dll.telem_amd_close(h_context)
            return False

        native_timing_values = [c_double(0.0) for _ in range(14)]
        native_dll.telem_amd_get_last_frame_timings(
            h_context, *(byref(value) for value in native_timing_values)
        )
        native_timing_names = (
            "MF ReadSample/decode availability",
            "MF decoder surface acquisition",
            "Decoder surface GPU copy",
            "Native HUD CPU copy",
            "HUD texture upload",
            "NV12 staging memcpy",
            "BlendRGBAToNV12",
            "CopyResource submission",
            "VideoProcessor CPU submit",
            "VideoProcessor GPU completion",
            "GPU wait/synchronization",
            "AMF submit/backpressure",
            "AMF QueryOutput",
            "Packet write",
        )
        for name, value in zip(native_timing_names, native_timing_values):
            if name == "BlendRGBAToNV12" and not hud_work_enabled:
                continue
            timing_samples[name].append(float(value.value))
        if hud_work_enabled:
            native_copy_ms = float(native_timing_values[3].value)
            native_upload_ms = float(native_timing_values[4].value)
            timing_samples["Python->native bridge"].append(
                max(0.0, last_hud_call_ms - native_copy_ms - native_upload_ms)
            )

        if diagnostics_enabled and frame_idx == 30:
            native_dll.telem_amd_dump_checkpoint(h_context, 30, b"E_amf_input", os.path.abspath("E_amf_input.png"))

        # Progress reporting
        if (frame_idx + 1) % progress_interval == 0 or (frame_idx + 1) == expected_progress_frames:
            elapsed = time.time() - start_time
            fps = (frame_idx + 1) / elapsed if elapsed > 0 else 0
            eta = (expected_progress_frames - (frame_idx + 1)) / fps if fps > 0 else 0
            pct = int(((frame_idx + 1) / expected_progress_frames) * 100)
            m, s = divmod(int(elapsed), 60)
            em, es = divmod(int(eta), 60)
            stats_str = f"Render: {pct}% ({frame_idx+1}/{expected_progress_frames}) | {fps:.1f} FPS | {m:02d}:{s:02d} elapsed, ETA {em:02d}:{es:02d}"
            if progress_cb:
                progress_cb(frame_idx + 1, stats_str)
        frame_idx += 1

    if proc_dec:
        if proc_dec.stdout and hasattr(proc_dec.stdout, "close"):
            try:
                proc_dec.stdout.close()
            except Exception:
                pass
        try:
            proc_dec.wait()
        except Exception:
            pass

    # 4. Flush and Retrieve Stats
    flush_ok = native_dll.telem_amd_flush(h_context)
    if not flush_ok:
        print("[AMD NATIVE D3D11] ERROR: AMF drain/finalize failed.", flush=True)
        native_dll.telem_amd_close(h_context)
        return False

    c_decoded = c_uint64(0)
    c_vp = c_uint64(0)
    c_sub = c_uint64(0)
    c_rec = c_uint64(0)
    native_dll.telem_amd_get_stats(h_context, byref(c_decoded), byref(c_vp), byref(c_sub), byref(c_rec))

    c_hud_updates = c_uint64(0)
    c_video_updates = c_uint64(0)
    c_input_full = c_uint64(0)
    c_retries = c_uint64(0)
    c_dropped = c_uint64(0)
    c_ignored = c_uint64(0)
    native_dll.telem_amd_get_extended_stats(
        h_context,
        byref(c_hud_updates), byref(c_video_updates), byref(c_input_full),
        byref(c_retries), byref(c_dropped), byref(c_ignored),
    )
    c_blend_calls = c_uint64(0)
    c_gpu_profiled_frames = c_uint64(0)
    native_dll.telem_amd_get_etap1_stats(
        h_context, byref(c_blend_calls), byref(c_gpu_profiled_frames),
    )
    c_gpu_hud_frames = c_uint64(0)
    c_hud_texture_creates = c_uint64(0)
    c_hud_texture_uploads = c_uint64(0)
    c_native_hud_mode = c_int(-1)
    native_dll.telem_amd_get_etap2_stats(
        h_context,
        byref(c_gpu_hud_frames), byref(c_hud_texture_creates),
        byref(c_hud_texture_uploads), byref(c_native_hud_mode),
    )
    c_hud_uploaded_bytes = c_uint64(0)
    c_hud_uploaded_rects = c_uint64(0)
    native_dll.telem_amd_get_etap3_stats(
        h_context, byref(c_hud_uploaded_bytes), byref(c_hud_uploaded_rects),
    )
    etap4_uint64_stats = [c_uint64(0) for _ in range(9)]
    c_native_decode_mode = c_int(-1)
    c_hardware_decode_confirmed = c_int(0)
    c_decoder_format = c_uint(0)
    native_dll.telem_amd_get_etap4_stats(
        h_context,
        *(byref(value) for value in etap4_uint64_stats),
        byref(c_native_decode_mode),
        byref(c_hardware_decode_confirmed),
        byref(c_decoder_format),
    )
    (
        c_mf_read_calls,
        c_mf_video_samples,
        c_mf_stream_ticks,
        c_mf_null_samples,
        c_mf_d3d11_surfaces,
        c_mf_format_changes,
        c_mf_eos_events,
        c_direct_surface_frames,
        c_decoder_gpu_copy_frames,
    ) = etap4_uint64_stats
    decoder_format_name = {
        103: "DXGI_FORMAT_NV12",
        104: "DXGI_FORMAT_P010",
    }.get(c_decoder_format.value, f"DXGI_FORMAT_{c_decoder_format.value}")

    print("\n[AMD NATIVE D3D11 PIPELINE STATS]", flush=True)
    print(f"  Source metadata:  {source_frames}", flush=True)
    print(f"  Source requested: {total_frames}", flush=True)
    print(f"  Python decoded:   {decoded_frames_python}", flush=True)
    print(f"  Native processed: {c_decoded.value}", flush=True)
    print(f"  HUD frames:       {hud_frames}", flush=True)
    print(f"  HUD updates:      {c_hud_updates.value}", flush=True)
    print(f"  Video updates:    {c_video_updates.value}", flush=True)
    print(f"  VP processed:     {c_vp.value}", flush=True)
    print(f"  AMF submitted:    {c_sub.value}", flush=True)
    print(f"  AMF output:       {c_rec.value}", flush=True)
    print(f"  AMF_INPUT_FULL:   {c_input_full.value}", flush=True)
    print(f"  AMF retries:      {c_retries.value}", flush=True)
    print(f"  AMF dropped:      {c_dropped.value}", flush=True)
    print(f"  AMF ignored:      {c_ignored.value}", flush=True)
    print(f"  CPU blend calls:  {c_blend_calls.value}", flush=True)
    print(f"  GPU profiled:     {c_gpu_profiled_frames.value}", flush=True)
    print(f"  GPU HUD frames:   {c_gpu_hud_frames.value}", flush=True)
    print(f"  HUD tex creates:  {c_hud_texture_creates.value}", flush=True)
    print(f"  HUD tex uploads:  {c_hud_texture_uploads.value}", flush=True)
    print(f"  HUD upload bytes: {c_hud_uploaded_bytes.value}", flush=True)
    print(f"  HUD upload rects: {c_hud_uploaded_rects.value}", flush=True)
    print(f"  MF ReadSample:    {c_mf_read_calls.value}", flush=True)
    print(f"  MF video samples: {c_mf_video_samples.value}", flush=True)
    print(f"  MF stream ticks:  {c_mf_stream_ticks.value}", flush=True)
    print(f"  MF null samples:  {c_mf_null_samples.value}", flush=True)
    print(f"  MF D3D surfaces:  {c_mf_d3d11_surfaces.value}", flush=True)
    print(f"  MF format changes:{c_mf_format_changes.value}", flush=True)
    print(f"  MF EOS events:    {c_mf_eos_events.value}", flush=True)
    print(f"  Decoder direct VP:{c_direct_surface_frames.value}", flush=True)
    print(f"  Decoder GPU copy: {c_decoder_gpu_copy_frames.value}", flush=True)
    print(f"  Decoder format:   {decoder_format_name}", flush=True)
    print(
        f"  HW decode proof:  {'YES' if c_hardware_decode_confirmed.value else 'NO'}",
        flush=True,
    )

    native_dll.telem_amd_close(h_context)

    # 5. Final Fast Remux (Copy Video Stream + Copy Audio Stream - ZERO VIDEO RE-ENCODE)
    temp_h265 = output_file_str + ".h265"
    if not os.path.exists(temp_h265) or os.path.getsize(temp_h265) == 0:
        print(f"[AMD NATIVE D3D11] ERROR: Raw bitstream {temp_h265} is missing or empty!", flush=True)
        return False

    cmd_mux = [
        ffmpeg_exe, "-y",
        "-i", temp_h265,
        "-i", input_file_str,
        "-map", "0:v",
        "-map", "1:a?",
        "-c:v", "copy",
        "-c:a", "copy",
        output_file_str
    ]

    print("[AMD NATIVE D3D11] Muxing encoded video stream + audio (-c:v copy -c:a copy)...", flush=True)
    mux_start = time.perf_counter()
    proc = subprocess.run(cmd_mux, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    mux_elapsed_ms = (time.perf_counter() - mux_start) * 1000.0
    timing_samples["Audio mux"].append(mux_elapsed_ms)
    if proc.returncode != 0:
        print(f"[AMD NATIVE D3D11] WARNING: FFmpeg remux failed, renaming raw bitstream.", flush=True)
        if os.path.exists(output_file_str): os.remove(output_file_str)
        os.rename(temp_h265, output_file_str)
    else:
        print(f"[AMD NATIVE D3D11] Remux complete. Final output: {output_file_str}", flush=True)
        if os.path.exists(temp_h265):
            os.remove(temp_h265)

    end_to_end_elapsed = time.perf_counter() - end_to_end_start
    final_probe = _probe_video_summary(ffmpeg_exe, output_file_str)
    muxed_frames = _stream_frame_count(final_probe, "video")
    audio_present = any(
        stream.get("codec_type") == "audio" for stream in final_probe.get("streams", [])
    )
    true_fps = c_rec.value / end_to_end_elapsed if end_to_end_elapsed > 0 else 0.0
    timing_summaries = {
        name: _timing_summary(values) for name, values in timing_samples.items()
    }

    _print_timing_table(timing_summaries)
    print("\n[AMD NATIVE TRUE END-TO-END]", flush=True)
    print(f"  Total wall-clock: {end_to_end_elapsed:.3f} s", flush=True)
    print(f"  Encoded frames:   {c_rec.value}", flush=True)
    print(f"  TRUE FPS:         {true_fps:.3f}", flush=True)
    print(f"  Muxed frames:     {muxed_frames}", flush=True)
    print(f"  Audio present:    {'YES' if audio_present else 'NO'}", flush=True)

    profile = {
        "schema_version": 1,
        "backend": f"AMD_NATIVE_D3D11_{native_hud_mode}_{native_decode_mode}",
        "dll": {
            "path": dll_path,
            "abi_version": loaded_abi,
            "build_info": build_info,
            "build_id": build_id,
            "build_timestamp": embedded_build_time,
            "file_timestamp": file_build_time,
        },
        "diagnostics_enabled": diagnostics_enabled,
        "profiling_enabled": profiling_enabled,
        "hud_enabled": hud_enabled,
        "legacy_no_hud_benchmark": legacy_no_hud,
        "input": input_probe,
        "output": final_probe,
        "frame_accounting": {
            "source_frames": source_frames,
            "requested_frames": total_frames,
            "decoded_frames": decoded_frames_python,
            "mf_read_sample_calls": c_mf_read_calls.value,
            "mf_video_samples": c_mf_video_samples.value,
            "mf_stream_ticks": c_mf_stream_ticks.value,
            "mf_null_samples": c_mf_null_samples.value,
            "mf_d3d11_surfaces": c_mf_d3d11_surfaces.value,
            "hud_frames": hud_frames,
            "python_hud_updates": successful_hud_updates,
            "python_video_updates": successful_video_updates,
            "native_processed": c_decoded.value,
            "native_hud_updates": c_hud_updates.value,
            "native_video_updates": c_video_updates.value,
            "vp_processed": c_vp.value,
            "amf_submitted": c_sub.value,
            "amf_output": c_rec.value,
            "muxed_frames": muxed_frames,
        },
        "amf": {
            "input_full_count": c_input_full.value,
            "retry_count": c_retries.value,
            "dropped_submissions": c_dropped.value,
            "ignored_submissions": c_ignored.value,
        },
        "etap1": {
            "blend_calls": c_blend_calls.value,
            "gpu_profiled_frames": c_gpu_profiled_frames.value,
            "production_gpu_wait_removed": not profiling_enabled,
        },
        "etap2": {
            "hud_mode": native_hud_mode,
            "native_hud_mode": c_native_hud_mode.value,
            "gpu_hud_frames": c_gpu_hud_frames.value,
            "hud_texture_creates": c_hud_texture_creates.value,
            "hud_texture_uploads": c_hud_texture_uploads.value,
            "python_hud_format": "RGBA straight alpha",
            "hud_upload_format": "RGBA",
            "hud_texture_format": "DXGI_FORMAT_R8G8B8A8_UNORM",
            "gpu_compositor": "DIRECT_NV12_COMPUTE_SHADER",
            "hud_texture_persistent": c_hud_texture_creates.value <= 1,
        },
        "etap3": {
            "upload_mode": hud_upload_mode if native_hud_mode == "GPU_HUD" else "CPU_REFERENCE_LEGACY",
            "dirty_max_rects": dirty_max_rects,
            "full_pil_tobytes_calls": len(timing_samples["PIL tobytes"]),
            "pillow_buffer_protocol_writable": False,
            "image_and_backing_share_memory": False,
            "fallback_reason": (
                "Pillow RGBA frombuffer is readonly and detaches on first draw"
                if native_hud_mode == "GPU_HUD" else "not applicable"
            ),
            "backing_buffer_address": hex(hud_backing_address) if hud_backing_address else None,
            "pointer_sent_first": hex(hud_pointer_observations[0]) if hud_pointer_observations else None,
            "pointer_sent_last": hex(hud_pointer_observations[-1]) if hud_pointer_observations else None,
            "pointer_stable": len(set(hud_pointer_observations)) <= 1,
            "native_full_memcpy": native_hud_mode != "GPU_HUD",
            "native_uploaded_bytes_total": c_hud_uploaded_bytes.value,
            "native_uploaded_rects_total": c_hud_uploaded_rects.value,
            "rects_per_frame": _value_summary([float(value) for value in dirty_rect_counts]),
            "requested_upload_bytes_per_frame": _value_summary(
                [float(value) for value in requested_upload_bytes]
            ),
            "pillow_intermediate_bytes_per_frame": _value_summary(
                [float(value) for value in pillow_intermediate_bytes]
            ),
            "python_persistent_copy_bytes_per_frame": _value_summary(
                [float(value) for value in python_persistent_copy_bytes]
            ),
        },
        "etap4": {
            "decode_mode": native_decode_mode,
            "native_decode_mode": c_native_decode_mode.value,
            "hardware_acceleration_confirmed": bool(c_hardware_decode_confirmed.value),
            "decoder_output_format": decoder_format_name,
            "source_rotation_degrees": source_rotation,
            "rawvideo_pipe": not use_d3d11va,
            "ffmpeg_rawvideo_frames": decoded_frames_python if not use_d3d11va else 0,
            "cpu_raw_base_bytes_per_frame": frame_size if not use_d3d11va else 0,
            "cpu_to_gpu_base_bytes_per_frame": frame_size if not use_d3d11va else 0,
            "gpu_to_cpu_base_bytes_per_frame": 0,
            "staging_upload": not use_d3d11va,
            "mf_read_sample_calls": c_mf_read_calls.value,
            "mf_video_samples": c_mf_video_samples.value,
            "mf_stream_ticks": c_mf_stream_ticks.value,
            "mf_null_samples": c_mf_null_samples.value,
            "mf_d3d11_surfaces": c_mf_d3d11_surfaces.value,
            "mf_format_changes": c_mf_format_changes.value,
            "mf_eos_events": c_mf_eos_events.value,
            "direct_decoder_surface_to_vp_frames": c_direct_surface_frames.value,
            "decoder_gpu_copy_frames": c_decoder_gpu_copy_frames.value,
            "selected_timestamps": sample_timestamps,
        },
        "etap5a": overlay_profiler.summary(),
        "etap5b": {
            **fit_field_plan,
            "resolve_cache_value_calls": (
                int(fit_resolve_stats.get("calls", 0))
                if fit_resolve_stats is not None else None
            ),
            "resolve_cache_value_calls_per_frame": (
                float(fit_resolve_stats.get("calls", 0)) / max(1, hud_frames)
                if fit_resolve_stats is not None else None
            ),
            "resolve_calls_per_field": (
                dict(fit_resolve_stats.get("per_field", {}))
                if fit_resolve_stats is not None else {}
            ),
            "duplicate_field_lookups": (
                max(
                    0,
                    int(fit_resolve_stats.get("calls", 0))
                    - hud_frames * len(fit_field_plan["unique_resolve_fields"]),
                )
                if fit_resolve_stats is not None else None
            ),
        },
        "timings": timing_summaries,
        "total_wall_clock_s": end_to_end_elapsed,
        "true_fps": true_fps,
        "audio_present": audio_present,
        "hud_pipeline_calls": {
            "compose_overlay": len(timing_samples["compose_overlay"]),
            "tobytes": len(timing_samples["PIL tobytes"]),
            "update_hud": c_hud_updates.value,
            "blend_rgba_to_nv12": c_blend_calls.value,
        },
    }
    profile_path = output_file_str + ".amd_profile.json"
    try:
        with open(profile_path, "w", encoding="utf-8") as profile_file:
            json.dump(profile, profile_file, indent=2, ensure_ascii=False)
        print(f"[AMD NATIVE] Profiling JSON: {profile_path}", flush=True)
    except Exception as exc:
        print(f"[AMD NATIVE] WARNING: failed to write profiling JSON: {exc}", flush=True)

    # Dump Checkpoint F (Frame 30 from final encoded MP4)
    if diagnostics_enabled and os.path.exists(output_file_str):
        cmd_thumb = [
            ffmpeg_exe, "-y",
            "-i", output_file_str,
            "-vf", "select=eq(n\\,30)",
            "-vframes", "1",
            "F_final_mp4.png"
        ]
        subprocess.run(cmd_thumb, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        print("[CHECKPOINT] Saved F_final_mp4.png", flush=True)

    return True
