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
from src.indicators.moving_map import render_map_working_image
from src.ffmpeg.worker_cache import init_worker, _resolve_cache_value, WORKER_CACHE


AMD_NATIVE_ABI_VERSION = 8

_AMD_HUD_MODES = {"CPU_REFERENCE": 0, "GPU_HUD": 1}
_AMD_DECODE_MODES = {
    "GPU_HUD_CPU_DECODE_REFERENCE": 0,
    "CPU_DECODE_REFERENCE": 0,
    "GPU_HUD_D3D11VA": 1,
    "D3D11VA": 1,
}
# ETAP 5G — GPU map resize/composite.  CPU_REFERENCE keeps the map in the
# Pillow HUD (unchanged); GPU uploads the 692x692 working map and resizes +
# composites it on the GPU.  Filter: 0=bilinear, 1=bicubic, 2=Lanczos-3.
_AMD_MAP_FILTERS = {"BILINEAR": 0, "BICUBIC": 1, "LANCZOS": 2}

# ETAP 5J — GPU final compositing for the cadence/HR charts.  CPU_REFERENCE
# keeps both charts in the Pillow HUD (unchanged).  GPU renders the exact same
# chart RGBA on the CPU but uploads it to a persistent GPU texture and blends
# it into the GPU HUD canvas (straight-alpha "over", no resample), so the
# charts leave the Pillow final HUD AND the CPU dirty HUD upload.  GPU_SPLIT
# (ETAP 5K) uploads a static 1160x511 layer once per cache invalidation and
# only small dynamic cursor/value tiles per frame (replaced into the HUD).
_AMD_CHART_PATHS = {"CPU_REFERENCE": 0, "GPU": 1, "GPU_SPLIT": 2}
# Native chart texture slot index per indicator key.
_CHART_GPU_SLOTS = {"fit_cadence_text": 0, "fit_heart_rate_text": 1}

# ETAP 5L — GPU final compositing for the speed gauge.  CPU_REFERENCE keeps the
# gauge in the Pillow HUD (unchanged).  GPU renders the exact same gauge RGBA
# on the CPU but uploads it to a persistent GPU texture and blends it into the
# GPU HUD canvas (straight-alpha "over", no resample), analogous to 5J.
_AMD_GAUGE_PATHS = {"CPU_REFERENCE": 0, "GPU": 1}
_GAUGE_KEY = "fit_enhanced_speed_text"


def _gauge_gpu_layout_safe(
    gauge_bbox: Optional[tuple[int, int, int, int]],
    other_bboxes: dict[str, tuple[int, int, int, int]],
    chart_capture: dict[str, dict[str, Any]],
    map_dst: Optional[tuple[int, int, int, int]],
) -> tuple[bool, str]:
    """ETAP 5L z-order guard for the GPU gauge composite.

    The GPU gauge blend runs after the CPU HUD uploads and the GPU charts, and
    before the GPU map.  That reproduces the Pillow result only when the gauge
    bbox is disjoint from every other active widget bbox (and the GPU map dst),
    otherwise the GPU composite would change the z-order.  Unsafe layouts fall
    back to CPU_REFERENCE.
    """
    if gauge_bbox is None:
        return False, "gauge not rendered"
    boxes: list[tuple[int, int, int, int]] = []
    for key, bbox in other_bboxes.items():
        if key == _GAUGE_KEY:
            continue
        boxes.append(tuple(int(v) for v in bbox))
    for cap in chart_capture.values():
        if "bbox" in cap:
            boxes.append(tuple(int(v) for v in cap["bbox"]))
    if map_dst is not None:
        boxes.append(tuple(int(v) for v in map_dst))
    gx, gy, gw, gh = tuple(int(v) for v in gauge_bbox)
    for bx, by, bw, bh in boxes:
        if gx < bx + bw and bx < gx + gw and gy < by + bh and by < gy + gh:
            return False, f"gauge overlaps widget bbox=({bx},{by},{bw},{bh})"
    return True, "gauge z-order disjoint -> GPU safe"


def _chart_gpu_layout_safe(
    bboxes: dict[str, tuple[int, int, int, int]],
    chart_capture: dict[str, dict[str, Any]],
    map_dst: Optional[tuple[int, int, int, int]],
) -> tuple[set[str], str]:
    """ETAP 5J z-order guard for GPU chart compositing (analogous to the 5G
    map guard).

    The GPU chart blend runs *after* the CPU dirty HUD uploads and clears its
    own bbox inside the GPU HUD canvas.  That reproduces the Pillow result only
    when the chart bbox is disjoint from every other active indicator bbox
    (and from the GPU map dst).  If any widget overlaps a chart, moving that
    chart to the GPU would either sit it on top of a later-drawn widget or wipe
    an earlier-drawn widget's pixels — both change z-order.  Such charts must
    stay on the CPU path (automatic fallback).
    """
    safe: set[str] = set()
    other_boxes: list[tuple[int, int, int, int]] = list(bboxes.values())
    if map_dst is not None:
        other_boxes.append(tuple(int(v) for v in map_dst))
    reasons: list[str] = []
    for key, cap in chart_capture.items():
        if "bbox" not in cap:
            reasons.append(f"{key}: no bbox (not rendered)")
            continue
        if cap.get("rotation", 0) % 360 != 0:
            # The GPU blend cannot reproduce Pillow's rotation of the widget,
            # so a rotated chart must stay on the CPU path.
            reasons.append(f"{key}: non-zero rotation -> CPU_REFERENCE")
            continue
        cbox = tuple(int(v) for v in cap["bbox"])
        cx, cy, cw, ch = cbox
        overlap = False
        for bx, by, bw, bh in other_boxes:
            if cx < bx + bw and bx < cx + cw and cy < by + bh and by < cy + ch:
                overlap = True
                reasons.append(f"{key} overlaps widget bbox=({bx},{by},{bw},{bh})")
                break
        if not overlap:
            safe.add(key)
    if not chart_capture:
        return set(), "no active chart widgets"
    if not safe:
        return set(), "GPU_CHART_UNSAFE_LAYOUT -> all charts CPU_REFERENCE: " + "; ".join(reasons)
    if len(safe) < len(chart_capture):
        return safe, "partial fallback -> CPU_REFERENCE: " + "; ".join(reasons)
    return safe, "all active charts are z-order disjoint -> GPU safe"


def _map_gpu_layout_safe(layout: dict) -> tuple[bool, str]:
    """ETAP 5G z-order guard.  The GPU map path blends the map on top of the
    GPU HUD canvas.  That reproduces the Pillow result only when track_map is
    the last rendered indicator (drawn on top).  Any other ordering -> the
    caller must fall back to CPU_REFERENCE."""
    indicators = layout.get("indicators", {})
    if "track_map" not in indicators or not indicators["track_map"].get("enabled", True):
        return True, "no active track_map"
    enabled_keys = [k for k, cfg in indicators.items() if cfg and cfg.get("enabled", True)]
    if not enabled_keys:
        return True, "no active indicators"
    if enabled_keys[-1] != "track_map":
        return False, (
            f"track_map is not the last rendered indicator (last={enabled_keys[-1]}); "
            "GPU map-on-top would change z-order -> CPU_REFERENCE fallback"
        )
    return True, "track_map is the last rendered indicator"


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


class _FrameAccountant:
    """ETAP 5P — opt-in per-frame exclusive wall-clock accounting.

    ``AMD_FRAME_ACCOUNTING=1`` partitions each main-loop iteration into exclusive
    stages via ``perf_counter_ns`` so that
        frame_total == sum(exclusive stages) + unaccounted.
    The default (disabled) path only performs a few no-op method calls.
    """

    def __init__(self, enabled: bool) -> None:
        self.enabled = enabled
        self.trace: list[dict] = []
        self.stages: dict[str, int] | None = None
        self._last = 0
        self._begin = 0
        self._frame_idx = 0
        self.mark_calls = 0
        self.gc_pauses: list[tuple[int, float]] = []
        self._gc_start: float | None = None
        self._gc_cb_ref = None
        if enabled:
            import gc
            self._gc_cb_ref = self._gc_cb
            gc.callbacks.append(self._gc_cb_ref)

    def _gc_cb(self, phase, info):
        if phase == "start":
            self._gc_start = time.perf_counter()
        elif phase == "stop" and self._gc_start is not None:
            self.gc_pauses.append((
                int(info.get("generation", -1)),
                (time.perf_counter() - self._gc_start) * 1000.0,
            ))
            self._gc_start = None

    def begin_frame(self, frame_idx: int) -> None:
        if not self.enabled:
            return
        self._frame_idx = frame_idx
        self._begin = time.perf_counter_ns()
        self._last = self._begin
        self.stages = {}

    def mark(self, name: str) -> None:
        if not self.enabled or self.stages is None:
            return
        now = time.perf_counter_ns()
        self.stages[name] = self.stages.get(name, 0) + (now - self._last)
        self._last = now
        self.mark_calls += 1

    def end_frame(self) -> None:
        if not self.enabled or self.stages is None:
            return
        end_ns = time.perf_counter_ns()
        total = end_ns - self._begin
        measured = sum(self.stages.values())
        self.trace.append({
            "frame": self._frame_idx,
            "total_ns": total,
            "stages": dict(self.stages),
            "unaccounted_ns": total - measured,
        })
        self.stages = None


def _pct_sorted(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    x = sorted(values)
    return x[min(len(x) - 1, int(len(x) * p))]


def _frame_accounting_summary(acct: "_FrameAccountant") -> dict:
    """Median/P95/P99 summaries from the per-frame trace + GC stats."""
    if not acct.enabled or not acct.trace:
        return {"enabled": bool(acct.enabled), "frames": 0}
    frames = acct.trace
    totals = [f["total_ns"] / 1e6 for f in frames]
    unacct = [f["unaccounted_ns"] / 1e6 for f in frames]
    stage_names = sorted({k for f in frames for k in f["stages"]})
    stages = {}
    for name in stage_names:
        vals = [f["stages"].get(name, 0) / 1e6 for f in frames]
        stages[name] = {
            "median_ms": _pct_sorted(vals, 0.5),
            "p95_ms": _pct_sorted(vals, 0.95),
            "p99_ms": _pct_sorted(vals, 0.99),
            "avg_ms": sum(vals) / len(vals),
        }
    measured_med = sum(s["median_ms"] for s in stages.values())
    total_med = _pct_sorted(totals, 0.5)
    unaccounted_med = _pct_sorted(unacct, 0.5)
    accounted = (1.0 - unaccounted_med / total_med) * 100.0 if total_med > 0 else 0.0
    pauses = acct.gc_pauses
    gc_summary = {
        "collections": len(pauses),
        "collections_per_frame": len(pauses) / len(frames),
        "total_pause_ms": sum(p for _, p in pauses),
        "max_pause_ms": max((p for _, p in pauses), default=0.0),
        "avg_pause_ms": (sum(p for _, p in pauses) / len(pauses)) if pauses else 0.0,
    }
    return {
        "enabled": True,
        "frames": len(frames),
        "frame_total_ms": {
            "median": total_med,
            "p95": _pct_sorted(totals, 0.95),
            "p99": _pct_sorted(totals, 0.99),
            "avg": sum(totals) / len(totals),
        },
        "measured_sum_median_ms": measured_med,
        "unaccounted_ms": {
            "median": unaccounted_med,
            "p95": _pct_sorted(unacct, 0.95),
            "p99": _pct_sorted(unacct, 0.99),
            "max": max(unacct),
            "pct_of_frame": (unaccounted_med / total_med * 100.0) if total_med > 0 else 0.0,
        },
        "accounted_pct": accounted,
        "stages": stages,
        "gc": gc_summary,
        "estimated_instrumentation_overhead_us": acct.mark_calls * 0.06,
    }


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
    # ETAP 5H: regional CPU bridge mode.  REFERENCE = original crop -> np.asarray
    # -> np.copyto chain.  OPTIMIZED = crop -> tobytes -> ctypes.memmove directly
    # into the persistent backing buffer (no NumPy intermediate, fewer allocations).
    # Both modes must produce byte-identical backing contents.
    hud_buffer_mode = os.environ.get("AMD_HUD_BUFFER_MODE", "REFERENCE").strip().upper()
    if hud_buffer_mode not in {"REFERENCE", "OPTIMIZED"}:
        print(
            "[AMD NATIVE D3D11] ERROR: AMD_HUD_BUFFER_MODE must be REFERENCE or OPTIMIZED.",
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

    # ── ETAP 5G: GPU map resize/composite ───────────────────────────────
    # CPU_REFERENCE keeps the map in the Pillow HUD (unchanged).  GPU uploads
    # the 692x692 working map and resizes + composites it on the GPU.  The
    # z-order guard falls back to CPU_REFERENCE for unsafe layouts.
    requested_map_path = os.environ.get("AMD_MAP_PATH", "CPU_REFERENCE").strip().upper()
    if requested_map_path not in {"CPU_REFERENCE", "GPU"}:
        print("[AMD NATIVE D3D11] ERROR: AMD_MAP_PATH must be CPU_REFERENCE or GPU.", flush=True)
        return False
    map_gpu_safe, map_gpu_reason = _map_gpu_layout_safe(layout)
    gpu_map_enabled = requested_map_path == "GPU" and map_gpu_safe
    if requested_map_path == "GPU" and not map_gpu_safe:
        print(
            f"[AMD NATIVE D3D11] GPU_MAP_UNSAFE_LAYOUT -> CPU_REFERENCE fallback: {map_gpu_reason}",
            flush=True,
        )
    map_filter_name = os.environ.get("AMD_MAP_FILTER", "LANCZOS").strip().upper()
    if map_filter_name not in _AMD_MAP_FILTERS:
        map_filter_name = "LANCZOS"
    map_filter = _AMD_MAP_FILTERS[map_filter_name]
    # Diagnostic-only raw 691x691 map A/B (GPU resample vs Pillow LANCZOS).
    map_ab_readback = _env_flag("AMD_MAP_AB_READBACK", False)
    # Diagnostic-only ETAP 5J chart A/B (GPU-blended chart region read back from
    # the HUD canvas vs the exact CPU chart RGBA it was built from).
    chart_ab_readback = _env_flag("AMD_CHART_AB_READBACK", False)
    chart_static_readback = _env_flag("AMD_CHART_STATIC_READBACK", False)
    # Diagnostic-only ETAP 5L gauge A/B (GPU-blended gauge bbox read back from
    # the HUD canvas vs the CPU_REFERENCE result: raw gauge RGBA with dirty
    # zeros dropped, i.e. Pillow alpha_composite semantics).
    gauge_ab_readback = _env_flag("AMD_GAUGE_AB_READBACK", False)
    # Diagnostic-only native map upload / resize+blend submit timing capture.
    map_stats_enabled = _env_flag("AMD_MAP_STATS", False)
    print(
        f"[AMD NATIVE D3D11] AMD_MAP_PATH: {requested_map_path} "
        f"({'GPU' if gpu_map_enabled else 'CPU_REFERENCE'} active; reason: {map_gpu_reason})",
        flush=True,
    )
    if gpu_map_enabled:
        print(
            f"[AMD NATIVE D3D11] GPU map filter: {map_filter_name} ({map_filter})",
            flush=True,
        )

    # ETAP 5G: in GPU map mode the track_map widget leaves the Pillow HUD; the
    # CPU still renders its 692x692 working image, which is uploaded and
    # resized/composited on the GPU.  Everything else keeps the 5E path.
    compose_layout = layout
    if gpu_map_enabled and "track_map" in layout.get("indicators", {}):
        compose_layout = copy.deepcopy(layout)
        del compose_layout["indicators"]["track_map"]

    # ── ETAP 5J: GPU chart compositing ─────────────────────────────────
    # CPU_REFERENCE keeps both charts in the Pillow HUD (unchanged).  GPU
    # renders the exact same chart RGBA on the CPU but blends it into the GPU
    # HUD canvas instead.  The actual safe-chart set is computed at runtime
    # from a probe frame by the z-order guard (with automatic fallback for any
    # chart that overlaps another widget / the GPU map).
    requested_chart_path = os.environ.get("AMD_CHART_PATH", "CPU_REFERENCE").strip().upper()
    if requested_chart_path not in _AMD_CHART_PATHS:
        print("[AMD NATIVE D3D11] ERROR: AMD_CHART_PATH must be CPU_REFERENCE, GPU or GPU_SPLIT.", flush=True)
        return False
    gpu_charts_requested = requested_chart_path in ("GPU", "GPU_SPLIT")
    gpu_charts_split = requested_chart_path == "GPU_SPLIT"
    chart_mode_value = _AMD_CHART_PATHS[requested_chart_path]
    print(f"[AMD NATIVE D3D11] AMD_CHART_PATH: {requested_chart_path}", flush=True)

    # ── ETAP 5L: GPU gauge compositing ─────────────────────────────────
    requested_gauge_path = os.environ.get("AMD_GAUGE_PATH", "CPU_REFERENCE").strip().upper()
    if requested_gauge_path not in _AMD_GAUGE_PATHS:
        print("[AMD NATIVE D3D11] ERROR: AMD_GAUGE_PATH must be CPU_REFERENCE or GPU.", flush=True)
        return False
    gauge_gpu_requested = requested_gauge_path == "GPU"
    print(f"[AMD NATIVE D3D11] AMD_GAUGE_PATH: {requested_gauge_path}", flush=True)

    # ── ETAP 5N: telemetry mode (precomputed frame cache) ──────────────
    telemetry_mode = os.environ.get("AMD_TELEMETRY_MODE", "REFERENCE").strip().upper()
    if telemetry_mode not in {"REFERENCE", "PRECOMPUTED"}:
        print("[AMD NATIVE D3D11] ERROR: AMD_TELEMETRY_MODE must be REFERENCE or PRECOMPUTED.", flush=True)
        return False
    print(f"[AMD NATIVE D3D11] AMD_TELEMETRY_MODE: {telemetry_mode}", flush=True)

    # ── ETAP 5O/5U: AMF diagnostics (measurement only, no encoder changes) ──
    amf_mode = os.environ.get("AMD_AMF_MODE", "ENCODE").strip().upper()
    if amf_mode not in {"ENCODE", "BYPASS", "SUBMIT_NO_MUX"}:
        print("[AMD NATIVE D3D11] ERROR: AMD_AMF_MODE must be ENCODE, BYPASS or SUBMIT_NO_MUX.", flush=True)
        return False
    amf_diag_enabled = _env_flag("AMD_AMF_DIAG", False)
    print(f"[AMD NATIVE D3D11] AMD_AMF_MODE: {amf_mode}  AMD_AMF_DIAG: {amf_diag_enabled}", flush=True)
    fa_enabled = _env_flag("AMD_FRAME_ACCOUNTING", False)
    print(f"[AMD NATIVE D3D11] AMD_FRAME_ACCOUNTING: {'ON' if fa_enabled else 'OFF'}", flush=True)

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
    print(f"AMD Native HUD buffer mode: {hud_buffer_mode}", flush=True)

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

    # ETAP 5G — GPU map resize/composite
    native_dll.telem_amd_set_map_mode.restype = c_int
    native_dll.telem_amd_set_map_mode.argtypes = [c_void_p, c_int]

    native_dll.telem_amd_set_map_filter.restype = c_int
    native_dll.telem_amd_set_map_filter.argtypes = [c_void_p, c_int]

    native_dll.telem_amd_set_map_geometry.restype = c_int
    native_dll.telem_amd_set_map_geometry.argtypes = [
        c_void_p, c_uint, c_uint, c_uint, c_uint, c_uint, c_uint,
    ]

    native_dll.telem_amd_update_map.restype = c_int
    native_dll.telem_amd_update_map.argtypes = [
        c_void_p, ctypes.c_char_p, c_uint, c_uint, c_uint,
        POINTER(c_uint64), POINTER(c_int),
    ]

    native_dll.telem_amd_get_map_stats.restype = None
    native_dll.telem_amd_get_map_stats.argtypes = [
        c_void_p, POINTER(c_uint64), POINTER(c_uint64), POINTER(c_uint64),
        POINTER(c_double), POINTER(c_double), POINTER(c_double),
    ]

    native_dll.telem_amd_get_map_resample.restype = c_int
    native_dll.telem_amd_get_map_resample.argtypes = [c_void_p, POINTER(c_uint8), c_uint]

    # ── ETAP 5J / 5K — GPU chart compositing ───────────────────────────
    native_dll.telem_amd_set_chart_mode.restype = c_int
    native_dll.telem_amd_set_chart_mode.argtypes = [c_void_p, c_int]

    native_dll.telem_amd_update_chart.restype = c_int
    native_dll.telem_amd_update_chart.argtypes = [
        c_void_p, c_int, ctypes.c_char_p, c_uint, c_uint, c_uint,
        c_uint, c_uint, POINTER(c_uint64), POINTER(c_int),
    ]

    # ETAP 5K — GPU_SPLIT static layer (once per cache invalidation).
    native_dll.telem_amd_update_chart_static.restype = c_int
    native_dll.telem_amd_update_chart_static.argtypes = [
        c_void_p, c_int, ctypes.c_char_p, c_uint, c_uint, c_uint,
        c_uint, c_uint, POINTER(c_uint64), POINTER(c_int),
    ]

    # ETAP 5K — GPU_SPLIT dynamic tile (region: 0 = cursor, 1 = value).
    native_dll.telem_amd_update_chart_dynamic.restype = c_int
    native_dll.telem_amd_update_chart_dynamic.argtypes = [
        c_void_p, c_int, c_int, ctypes.c_char_p, c_uint, c_uint, c_uint,
        c_uint, c_uint, POINTER(c_uint64),
    ]

    native_dll.telem_amd_get_chart_stats.restype = None
    native_dll.telem_amd_get_chart_stats.argtypes = [
        c_void_p, POINTER(c_uint64), POINTER(c_uint64), POINTER(c_uint64),
        POINTER(c_double), POINTER(c_double), POINTER(c_uint64),
        POINTER(c_uint64), POINTER(c_uint64), POINTER(c_uint64),
        POINTER(c_uint64),
    ]

    # Diagnostic A/B: read back a region of the persistent HUD canvas (never
    # used on the production export path).
    native_dll.telem_amd_get_hud_region_readback.restype = c_int
    native_dll.telem_amd_get_hud_region_readback.argtypes = [
        c_void_p, c_uint, c_uint, c_uint, c_uint, POINTER(c_uint8), c_uint,
    ]

    # ETAP 5K diagnostic: read back the persistent static chart texture (never
    # used on the production export path).
    native_dll.telem_amd_get_chart_static_readback.restype = c_int
    native_dll.telem_amd_get_chart_static_readback.argtypes = [
        c_void_p, c_int, POINTER(c_uint8), c_uint,
    ]

    # ── ETAP 5L — GPU gauge compositing ────────────────────────────────
    native_dll.telem_amd_set_gauge_mode.restype = c_int
    native_dll.telem_amd_set_gauge_mode.argtypes = [c_void_p, c_int]

    native_dll.telem_amd_update_gauge.restype = c_int
    native_dll.telem_amd_update_gauge.argtypes = [
        c_void_p, ctypes.c_char_p, c_uint, c_uint, c_uint,
        c_uint, c_uint, POINTER(c_uint64), POINTER(c_int),
    ]

    native_dll.telem_amd_get_gauge_stats.restype = None
    native_dll.telem_amd_get_gauge_stats.argtypes = [
        c_void_p, POINTER(c_uint64), POINTER(c_uint64),
        POINTER(c_double), POINTER(c_double), POINTER(c_uint64),
    ]

    native_dll.telem_amd_set_source_rotation.restype = c_int
    native_dll.telem_amd_set_source_rotation.argtypes = [c_void_p, c_uint]

    native_dll.telem_amd_set_decode_mode.restype = c_int
    native_dll.telem_amd_set_decode_mode.argtypes = [c_void_p, c_int]

    native_dll.telem_amd_set_amf_mode.restype = c_int
    native_dll.telem_amd_set_amf_mode.argtypes = [c_void_p, c_int]

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
            layout=compose_layout,
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

    # ── ETAP 5G: GPU map resize/composite ───────────────────────────────
    if not native_dll.telem_amd_set_map_mode(h_context, 1 if gpu_map_enabled else 0):
        print("[AMD NATIVE D3D11] ERROR: failed to configure GPU map mode.", flush=True)
        native_dll.telem_amd_close(h_context)
        return False
    if gpu_map_enabled:
        if not native_dll.telem_amd_set_map_filter(h_context, map_filter):
            print("[AMD NATIVE D3D11] ERROR: failed to configure GPU map filter.", flush=True)
            native_dll.telem_amd_close(h_context)
            return False

    # ── ETAP 5J / 5K: GPU chart compositing (0 = CPU_REFERENCE, 1 = GPU,
    # 2 = GPU_SPLIT) ───────────────────────────────────────────────────
    if not native_dll.telem_amd_set_chart_mode(h_context, chart_mode_value):
        print("[AMD NATIVE D3D11] ERROR: failed to configure GPU chart mode.", flush=True)
        native_dll.telem_amd_close(h_context)
        return False

    # ── ETAP 5L: GPU gauge compositing (1 = GPU, 0 = CPU_REFERENCE) ────
    if not native_dll.telem_amd_set_gauge_mode(h_context, 1 if gauge_gpu_requested else 0):
        print("[AMD NATIVE D3D11] ERROR: failed to configure GPU gauge mode.", flush=True)
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

    # ── ETAP 5U: AMF mode (0=ENCODE production, 1=BYPASS frontend-only). ──
    if amf_mode == "BYPASS":
        if not native_dll.telem_amd_set_amf_mode(h_context, 1):
            print("[AMD NATIVE D3D11] ERROR: failed to configure AMF BYPASS mode.", flush=True)
            native_dll.telem_amd_close(h_context)
            return False
        print("[AMD NATIVE D3D11] AMF BYPASS active: frontend D3D11/VP/compute only, "
              "no encode/mux.", flush=True)

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
        "map_cpu_upload": [],
        "GPU map upload (native)": [],
        "GPU map resize+blend submit": [],
        # ETAP 5J / 5K — GPU chart compositing
        "chart_cpu_tobytes": [],
        "chart_python_upload": [],
        "chart_dynamic_tobytes": [],
        "chart_dynamic_upload": [],
        # ETAP 5L — GPU gauge compositing
        "gauge_tobytes": [],
        "gauge_upload": [],
        "GPU gauge blend submit": [],
        "GPU chart blend submit": [],
        "HUD dirty bbox": [],
        "HUD dirty extract": [],
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
    # ETAP 5G — GPU map resize/composite counters
    map_geometry_set = False
    map_gpu_frames = 0
    map_uploaded_bytes_total = 0
    map_upload_times: list[float] = []
    # ETAP 5O — AMF queue diagnostics (frame_idx, wall_s, submitted, received,
    # input_full_total, retry_total).  Only collected when AMD_AMF_DIAG=1.
    amf_diag_samples: list[tuple[int, float, int, int, int, int]] = []
    amf_preflush_submitted = 0
    amf_preflush_received = 0
    amf_drain_ms = 0.0
    frame_acct = _FrameAccountant(fa_enabled)
    etap5p = None
    last_map_img = None
    last_map_dst = None
    map_ab_results: dict[str, list] = {"mae": [], "max": [], "n>1": [], "n>2": [], "n>4": [], "n>8": [], "n>16": []}
    # ETAP 5J — GPU chart compositing counters.  gpu_chart_keys is resolved on
    # frame 0 by the z-order guard (probe render) and stays fixed afterwards.
    gpu_chart_keys: set[str] = set()
    gpu_chart_reason = "disabled"
    chart_gpu_frames: dict[str, int] = {"fit_cadence_text": 0, "fit_heart_rate_text": 0}
    chart_uploaded_bytes_total = 0
    chart_geometry_set: set[str] = set()
    # ETAP 5K — GPU_SPLIT counters: static uploaded once per cache
    # invalidation; small dynamic tiles per frame.  The full-size tobytes
    # counter must stay 0 after the one-time static upload in GPU_SPLIT.
    chart_static_uploaded: set[str] = set()
    chart_static_uploads = 0
    chart_static_bytes_total = 0
    chart_dynamic_uploads = 0
    chart_dynamic_bytes_total = 0
    chart_full_tobytes_total = 0
    chart_split_frames = 0
    # ETAP 5L — GPU gauge compositing counters.  gauge_gpu_active is resolved
    # on frame 0 by the gauge z-order guard (probe render).
    gauge_gpu_active = False
    gauge_gpu_reason = "disabled"
    gauge_gpu_frames = 0
    gauge_uploaded_bytes_total = 0
    gauge_static_geometry_set = False
    # Diagnostic ETAP 5J chart A/B readback results.
    chart_ab_results: dict[str, dict[str, list]] = {
        k: {"mae": [], "max": [], "n>1": [], "n>2": [], "n>4": [], "n>8": [], "n>16": []}
        for k in ("fit_cadence_text", "fit_heart_rate_text")
    }
    # ETAP 5K diagnostic: raw static texture A/B (CPU FINAL_STATIC_CHART vs
    # GPU static texture readback).  Run once on frame 0 when enabled.
    chart_static_ab_results: dict[str, dict[str, float | int]] = {}
    # ETAP 5L diagnostic: GPU gauge composite A/B (HUD gauge bbox readback vs
    # CPU_REFERENCE result), accumulated per frame when enabled.
    gauge_ab_results: dict[str, list] = {
        "mae": [], "max": [], "n>0": [], "n>1": [], "n>2": [], "n>4": [], "n>8": [],
        "dirty_zeros": [], "partial_alpha": [],
    }

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

    # ── ETAP 5N: precomputed telemetry cache (PRECOMPUTED mode) ─────────
    # Live reference closure (used by REFERENCE mode and as the VFR fallback).
    def _live_frame_data(frame_idx, curr_dt, chart_data):
        return prepare_overlay_frame_data(
            layout=compose_layout,
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

    telemetry_cache = None
    if telemetry_mode == "PRECOMPUTED":
        from src.telemetry_precompute import build_telemetry_cache
        _pre_t0 = time.perf_counter()
        telemetry_cache = build_telemetry_cache(
            layout=compose_layout,
            base_dt=base_dt,
            tz_offset_hours=tz_offset_hours,
            start_dt_utc=base_dt,
            speed_samples=speed_samples,
            track_samples=track_samples,
            alt_samples=alt_samples,
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
            chart_data=WORKER_CACHE.get("_precomputed_chart_data", {}),
            resolve_cache_value=_resolve_cache_value,
            _range_cache=WORKER_CACHE.get("_prep_cache"),
            fit_field_plan=fit_field_plan,
            total_frames=total_frames,
            target_fps=target_fps,
        )
        print(
            f"[AMD NATIVE D3D11] AMD_TELEMETRY_MODE=PRECOMPUTED: "
            f"cache {telemetry_cache.frames} frames, build "
            f"{telemetry_cache.build_ms:.1f} ms, mem "
            f"{telemetry_cache.memory_bytes / (1024.0 * 1024.0):.3f} MiB",
            flush=True,
        )

    # Main Frame Processing Loop
    frame_idx = 0
    expected_progress_frames = source_frames if use_d3d11va and source_frames else total_frames
    while True:
        frame_acct.begin_frame(frame_idx)
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

        frame_acct.mark("loop_guard")
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

        frame_acct.mark("decode_read")
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
            frame_acct.mark("hud_setup")
            telemetry_start = time.perf_counter()
            if (
                telemetry_mode == "PRECOMPUTED"
                and telemetry_cache is not None
                and frame_idx < len(telemetry_cache.records)
                and abs(sample_time_seconds - frame_idx / target_fps) <= 1e-6
            ):
                # ETAP 5N hot path: cache lookup, zero interpolation/resolver.
                frame_kwargs = telemetry_cache.lookup(frame_idx)
            else:
                # REFERENCE mode, or VFR/out-of-range guard -> live path.
                frame_kwargs = _live_frame_data(frame_idx, curr_dt, chart_data)
            telemetry_elapsed_ms = (time.perf_counter() - telemetry_start) * 1000.0
            timing_samples["Telemetry/frame_data"].append(telemetry_elapsed_ms)
            overlay_profiler.record(
                "telemetry.prepare_overlay_frame_data", telemetry_elapsed_ms
            )
            frame_acct.mark("telemetry")
            if frame_idx % 30 == 0:
                print(f"Frame {frame_idx}: HR={frame_kwargs.get('hr_value')}, CAD={frame_kwargs.get('cad_value')}", flush=True)

            # ── ETAP 5J: resolve the GPU-safe chart set on frame 0 via a
            # single throwaway probe render (real bboxes), then keep it fixed.
            if frame_idx == 0 and gpu_charts_requested and not gpu_chart_keys:
                _probe_capture: dict[str, dict[str, Any]] = {}
                _probe_bboxes: dict[str, tuple[int, int, int, int]] = {}
                compose_overlay(
                    canvas_w=video_width, canvas_h=video_height,
                    layout=compose_layout, font_path=font_path,
                    _bboxes=_probe_bboxes,
                    gpu_capture_keys=set(_CHART_GPU_SLOTS.keys()),
                    gpu_capture=_probe_capture,
                    split_chart_keys=(
                        set(_CHART_GPU_SLOTS.keys()) if gpu_charts_split else None
                    ),
                    reuse_canvas=False,
                    **frame_kwargs,
                )
                _probe_map_dst = None
                if gpu_map_enabled:
                    _p_img, _p_dst = render_map_working_image(
                        video_width, video_height, layout, "track_map",
                        gps_track, target_dt=curr_dt,
                        current_position=frame_kwargs.get("current_position"),
                    )
                    _probe_map_dst = _p_dst
                gpu_chart_keys, gpu_chart_reason = _chart_gpu_layout_safe(
                    _probe_bboxes, _probe_capture, _probe_map_dst,
                )
                if gpu_chart_keys:
                    print(
                        f"[AMD NATIVE D3D11] GPU charts active: {sorted(gpu_chart_keys)} "
                        f"({gpu_chart_reason})",
                        flush=True,
                    )
                else:
                    print(
                        f"[AMD NATIVE D3D11] GPU charts fallback -> CPU_REFERENCE "
                        f"({gpu_chart_reason})",
                        flush=True,
                    )

                # ── ETAP 5L: resolve the GPU gauge safety on the same probe
                # frame (the gauge bbox is in _probe_bboxes since the probe only
                # captures the charts). ────────────────────────────────
                if gauge_gpu_requested:
                    _g_bbox = _probe_bboxes.get(_GAUGE_KEY)
                    gauge_gpu_active, gauge_gpu_reason = _gauge_gpu_layout_safe(
                        _g_bbox, _probe_bboxes, _probe_capture, _probe_map_dst,
                    )
                    print(
                        f"[AMD NATIVE D3D11] GPU gauge "
                        f"{'active' if gauge_gpu_active else 'fallback -> CPU_REFERENCE'} "
                        f"bbox={_g_bbox} ({gauge_gpu_reason})",
                        flush=True,
                    )
            frame_acct.mark("frame0_probe")
            _bboxes = {}
            gpu_capture: dict[str, dict[str, Any]] = {}
            # ETAP 5L: the gauge is captured alongside the charts (it leaves
            # the Pillow HUD and its CPU dirty upload when GPU-active).
            capture_keys = set(gpu_chart_keys)
            if gauge_gpu_active:
                capture_keys.add(_GAUGE_KEY)
            compose_start = time.perf_counter()
            composed_img = compose_overlay(
                canvas_w=video_width,
                canvas_h=video_height,
                layout=compose_layout,
                font_path=font_path,
                _bboxes=_bboxes,
                gpu_capture_keys=capture_keys,
                gpu_capture=gpu_capture,
                split_chart_keys=(gpu_chart_keys if gpu_charts_split else None),
                **frame_kwargs
            )
            compose_elapsed_ms = (time.perf_counter() - compose_start) * 1000.0
            timing_samples["compose_overlay"].append(compose_elapsed_ms)
            overlay_profiler.record("compose.total", compose_elapsed_ms)
            frame_acct.mark("compose")

            # ── ETAP 5J / 5K: upload the GPU charts to persistent textures. ──
            # GPU (5J): full 1160x511 chart RGBA per frame.  GPU_SPLIT (5K):
            # the static 1160x511 layer once per cache invalidation + small
            # dynamic cursor/value tiles per frame (no full per-frame upload).
            if gpu_capture:
                chart_to_bytes_ms = 0.0
                chart_upload_ms = 0.0
                chart_dyn_tobytes_ms = 0.0
                chart_dyn_upload_ms = 0.0
                for chart_key in gpu_chart_keys:
                    cap = gpu_capture.get(chart_key)
                    if cap is None:
                        continue
                    bx, by, bw, bh = cap["bbox"]
                    slot = _CHART_GPU_SLOTS[chart_key]
                    if gpu_charts_split and cap.get("split"):
                        # ── ETAP 5K: static once + dynamic tiles per frame ──
                        static_img = cap["static"]
                        if chart_key not in chart_static_uploaded:
                            tb_start = time.perf_counter()
                            st_bytes = static_img.tobytes("raw", "RGBA")
                            chart_full_tobytes_total += 1
                            chart_to_bytes_ms = max(
                                chart_to_bytes_ms,
                                (time.perf_counter() - tb_start) * 1000.0,
                            )
                            st_uploaded = c_uint64(0)
                            st_created = c_int(0)
                            up_start = time.perf_counter()
                            ok = native_dll.telem_amd_update_chart_static(
                                h_context, slot, st_bytes, static_img.width,
                                static_img.height, static_img.width * 4,
                                bx, by, byref(st_uploaded), byref(st_created),
                            )
                            chart_upload_ms = max(
                                chart_upload_ms,
                                (time.perf_counter() - up_start) * 1000.0,
                            )
                            if ok:
                                chart_static_uploaded.add(chart_key)
                                chart_static_uploads += 1
                                chart_static_bytes_total += int(st_uploaded.value)
                                if chart_static_readback and frame_idx == 0:
                                    sw, sh = static_img.width, static_img.height
                                    st_buf = (c_uint8 * (sw * sh * 4))()
                                    if native_dll.telem_amd_get_chart_static_readback(
                                        h_context, slot, st_buf, sw * 4,
                                    ):
                                        gpu_static = np.asarray(
                                            Image.frombuffer(
                                                "RGBA", (sw, sh), st_buf,
                                                "raw", "RGBA", 0, 1,
                                            ),
                                            dtype=np.int16,
                                        )
                                        cpu_static = np.asarray(
                                            static_img, dtype=np.int16)
                                        diff_s = np.abs(gpu_static - cpu_static)
                                        chart_static_ab_results[chart_key] = {
                                            "mae": float(diff_s.mean()),
                                            "max": int(diff_s.max()),
                                            "diff_px": int((diff_s.max(axis=2) > 0).sum()),
                                        }
                                        print(
                                            f"[AMD NATIVE D3D11] 5K raw static A/B "
                                            f"{chart_key}: MAE={diff_s.mean():.6f} "
                                            f"MAX={diff_s.max()} "
                                            f"diff_px={int((diff_s.max(axis=2) > 0).sum())}",
                                            flush=True,
                                        )
                            else:
                                print(
                                    f"[AMD NATIVE D3D11] ERROR: telem_amd_update_chart_static"
                                    f"({chart_key}) failed on frame {frame_idx}",
                                    flush=True,
                                )
                        # Cursor tile (region 0).
                        ct = cap["cursor_tile"]
                        if ct is not None:
                            c_up = c_uint64(0)
                            cl = cap["cursor_local"]
                            dyn_tb_start = time.perf_counter()
                            cbytes = ct.tobytes("raw", "RGBA")
                            chart_dyn_tobytes_ms = max(
                                chart_dyn_tobytes_ms,
                                (time.perf_counter() - dyn_tb_start) * 1000.0,
                            )
                            dyn_up_start = time.perf_counter()
                            ok = native_dll.telem_amd_update_chart_dynamic(
                                h_context, slot, 0, cbytes, ct.width, ct.height,
                                ct.width * 4, cl[0], cl[1], byref(c_up),
                            )
                            chart_dyn_upload_ms = max(
                                chart_dyn_upload_ms,
                                (time.perf_counter() - dyn_up_start) * 1000.0,
                            )
                            if ok:
                                chart_dynamic_uploads += 1
                                chart_dynamic_bytes_total += int(c_up.value)
                        # Value tile (region 1).
                        vt = cap["value_tile"]
                        if vt is not None:
                            v_up = c_uint64(0)
                            vl = cap["value_local"]
                            dyn_tb_start = time.perf_counter()
                            vbytes = vt.tobytes("raw", "RGBA")
                            chart_dyn_tobytes_ms = max(
                                chart_dyn_tobytes_ms,
                                (time.perf_counter() - dyn_tb_start) * 1000.0,
                            )
                            dyn_up_start = time.perf_counter()
                            ok = native_dll.telem_amd_update_chart_dynamic(
                                h_context, slot, 1, vbytes, vt.width, vt.height,
                                vt.width * 4, vl[0], vl[1], byref(v_up),
                            )
                            chart_dyn_upload_ms = max(
                                chart_dyn_upload_ms,
                                (time.perf_counter() - dyn_up_start) * 1000.0,
                            )
                            if ok:
                                chart_dynamic_uploads += 1
                                chart_dynamic_bytes_total += int(v_up.value)
                        chart_gpu_frames[chart_key] += 1
                        chart_split_frames += 1
                    else:
                        # ── ETAP 5J: full chart RGBA per frame ──
                        chart_img = cap.get("image")
                        if chart_img is None:
                            continue
                        tb_start = time.perf_counter()
                        chart_bytes = chart_img.tobytes("raw", "RGBA")
                        chart_full_tobytes_total += 1
                        chart_to_bytes_ms = max(
                            chart_to_bytes_ms,
                            (time.perf_counter() - tb_start) * 1000.0,
                        )
                        ch_uploaded = c_uint64(0)
                        ch_created = c_int(0)
                        up_start = time.perf_counter()
                        ok = native_dll.telem_amd_update_chart(
                            h_context, slot, chart_bytes, chart_img.width,
                            chart_img.height, chart_img.width * 4, bx, by,
                            byref(ch_uploaded), byref(ch_created),
                        )
                        chart_upload_ms = max(
                            chart_upload_ms,
                            (time.perf_counter() - up_start) * 1000.0,
                        )
                        if not ok:
                            print(
                                f"[AMD NATIVE D3D11] ERROR: telem_amd_update_chart({chart_key}) "
                                f"failed on frame {frame_idx}",
                                flush=True,
                            )
                        else:
                            chart_gpu_frames[chart_key] += 1
                            chart_uploaded_bytes_total += int(ch_uploaded.value)
                timing_samples["chart_cpu_tobytes"].append(chart_to_bytes_ms)
                timing_samples["chart_python_upload"].append(chart_upload_ms)
                frame_acct.mark("chart_upload")
                timing_samples["chart_dynamic_tobytes"].append(chart_dyn_tobytes_ms)
                timing_samples["chart_dynamic_upload"].append(chart_dyn_upload_ms)

            # ── ETAP 5L: upload the GPU speed gauge (exact CPU RGBA, final
            # size, 1:1 texel, no resample) to a persistent texture. ─────
            # The gauge bbox may extend beyond the HUD bounds (the layout
            # places it near the bottom edge); the CPU Pillow alpha_composite
            # clips it, so the GPU upload/blend must clip to the HUD too.
            gauge_ab_bbox = None
            gauge_ab_img = None
            if gauge_gpu_active:
                gauge_cap = gpu_capture.get(_GAUGE_KEY)
                gauge_tobytes_ms = 0.0
                gauge_upload_ms = 0.0
                if gauge_cap is not None and "image" in gauge_cap:
                    gauge_img = gauge_cap["image"]
                    gx, gy, gw, gh = gauge_cap["bbox"]
                    # Clip to the HUD bounds.
                    cx0, cy0 = max(0, gx), max(0, gy)
                    cx1, cy1 = min(video_width, gx + gw), min(video_height, gy + gh)
                    if cx1 > cx0 and cy1 > cy0:
                        gauge_img = gauge_img.crop((
                            cx0 - gx, cy0 - gy, cx1 - gx, cy1 - gy))
                        gx, gy, gw, gh = cx0, cy0, cx1 - cx0, cy1 - cy0
                        gauge_ab_bbox = (gx, gy, gw, gh)
                        gauge_ab_img = gauge_img
                        tb_start = time.perf_counter()
                        gauge_bytes = gauge_img.tobytes("raw", "RGBA")
                        gauge_tobytes_ms = (time.perf_counter() - tb_start) * 1000.0
                        g_uploaded = c_uint64(0)
                        g_created = c_int(0)
                        up_start = time.perf_counter()
                        ok = native_dll.telem_amd_update_gauge(
                            h_context, gauge_bytes, gauge_img.width, gauge_img.height,
                            gauge_img.width * 4, gx, gy,
                            byref(g_uploaded), byref(g_created),
                        )
                        gauge_upload_ms = (time.perf_counter() - up_start) * 1000.0
                        if not ok:
                            print(
                                f"[AMD NATIVE D3D11] ERROR: telem_amd_update_gauge "
                                f"failed on frame {frame_idx}",
                                flush=True,
                            )
                        else:
                            gauge_gpu_frames += 1
                            gauge_uploaded_bytes_total += int(g_uploaded.value)
                timing_samples["gauge_tobytes"].append(gauge_tobytes_ms)
                timing_samples["gauge_upload"].append(gauge_upload_ms)
                frame_acct.mark("gauge_upload")

            # ── ETAP 5G: GPU map resize/composite ────────────────────────
            if gpu_map_enabled:
                map_start = time.perf_counter()
                map_img, map_dst = render_map_working_image(
                    video_width, video_height, layout, "track_map",
                    gps_track, target_dt=curr_dt, current_position=frame_kwargs.get("current_position"),
                )
                if map_img is not None and map_dst is not None:
                    last_map_img = map_img
                    last_map_dst = map_dst
                    if not map_geometry_set:
                        map_geometry_set = True
                        dst_x, dst_y, out_w, out_h = map_dst
                        src_w, src_h = map_img.size
                        native_dll.telem_amd_set_map_geometry(
                            h_context, dst_x, dst_y, src_w, src_h, out_w, out_h,
                        )
                        print(
                            f"[AMD NATIVE D3D11] GPU map geometry: dst=({dst_x},{dst_y}) "
                            f"src={src_w}x{src_h} out={out_w}x{out_h}",
                            flush=True,
                        )
                    map_bytes = map_img.tobytes("raw", "RGBA")
                    map_upload_bytes = c_uint64(0)
                    map_tex_created = c_int(0)
                    upload_start = time.perf_counter()
                    ok = native_dll.telem_amd_update_map(
                        h_context, map_bytes, map_img.width, map_img.height,
                        map_img.width * 4, byref(map_upload_bytes), byref(map_tex_created),
                    )
                    map_upload_ms = (time.perf_counter() - upload_start) * 1000.0
                    if not ok:
                        print(
                            f"[AMD NATIVE D3D11] ERROR: telem_amd_update_map failed on frame {frame_idx}",
                            flush=True,
                        )
                    else:
                        map_uploaded_bytes_total += int(map_upload_bytes.value)
                        map_upload_times.append(map_upload_ms)
                        map_gpu_frames += 1
                map_timing = (time.perf_counter() - map_start) * 1000.0
                timing_samples["map_cpu_upload"].append(map_timing)
                if map_stats_enabled and gpu_map_enabled:
                    _ms_uploads = c_uint64(0)
                    _ms_bytes = c_uint64(0)
                    _ms_frames = c_uint64(0)
                    _ms_upload = c_double(0.0)
                    _ms_resample = c_double(0.0)
                    _ms_blend = c_double(0.0)
                    native_dll.telem_amd_get_map_stats(
                        h_context, byref(_ms_uploads), byref(_ms_bytes),
                        byref(_ms_frames), byref(_ms_upload),
                        byref(_ms_resample), byref(_ms_blend),
                    )
                    timing_samples["GPU map upload (native)"].append(float(_ms_upload.value))
                    timing_samples["GPU map resize+blend submit"].append(float(_ms_resample.value))
            frame_acct.mark("map_upload")
            overlay_profiler.finish_frame()
            hud_frames += 1

            if diagnostics_enabled and frame_idx in (30, 300, 900):
                if frame_idx == 30:
                    print("\n=== REAL GUI EXPORT TRACE (Frame 30) ===", flush=True)
                composed_img.save(f"01_python_hud_{frame_idx}.png")

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
                    bbox_start = time.perf_counter()
                    dirty_rects = _dirty_rects_from_bboxes(
                        previous_bboxes, _bboxes,
                        video_width, video_height, dirty_max_rects,
                    )
                    timing_samples["HUD dirty bbox"].append(
                        (time.perf_counter() - bbox_start) * 1000.0
                    )
                    intermediate_bytes = 0
                    persistent_copy_bytes = 0
                    upload_bytes = 0
                    if hud_buffer_mode == "OPTIMIZED":
                        # ETAP 5H OPTIMIZED: crop -> tobytes -> np.frombuffer
                        # (zero-copy view) -> np.copyto.  This avoids the extra
                        # internal copy np.asarray performs through Pillow's
                        # __array_interface__ (which returns a bytes blob and is
                        # copied again by numpy).  np.copyto keeps the strided
                        # backing write correct (a flat ctypes.memmove would
                        # misplace every row after the first — the row-stride
                        # trap).  Byte-for-byte identical to REFERENCE.
                        extract_start = time.perf_counter()
                        for x, y, rect_w, rect_h in dirty_rects:
                            region = composed_img.crop((x, y, x + rect_w, y + rect_h))
                            region_bytes = region.tobytes("raw", "RGBA")
                            region_array = np.frombuffer(
                                region_bytes, dtype=np.uint8
                            ).reshape(rect_h, rect_w, 4)
                            np.copyto(
                                hud_backing_view[y:y + rect_h, x:x + rect_w],
                                region_array,
                            )
                            persistent_copy_bytes += rect_w * rect_h * 4
                            upload_bytes += rect_w * rect_h * 4
                        timing_samples["HUD dirty extract"].append(
                            (time.perf_counter() - extract_start) * 1000.0
                        )
                    else:
                        # REFERENCE (original): crop -> np.asarray -> np.copyto.
                        extract_start = time.perf_counter()
                        for x, y, rect_w, rect_h in dirty_rects:
                            region = composed_img.crop((x, y, x + rect_w, y + rect_h))
                            region_array = np.asarray(region, dtype=np.uint8)
                            np.copyto(hud_backing_view[y:y + rect_h, x:x + rect_w], region_array)
                            region_bytes = rect_w * rect_h * 4
                            intermediate_bytes += region_bytes
                            persistent_copy_bytes += region_bytes
                            upload_bytes += region_bytes
                        timing_samples["HUD dirty extract"].append(
                            (time.perf_counter() - extract_start) * 1000.0
                        )
                    rect_count = len(dirty_rects)
                timing_samples["PIL/buffer preparation"].append(
                    (time.perf_counter() - buffer_prep_start) * 1000.0
                )
                pillow_intermediate_bytes.append(intermediate_bytes)
                python_persistent_copy_bytes.append(persistent_copy_bytes)
                requested_upload_bytes.append(upload_bytes)
                dirty_rect_counts.append(rect_count)
                previous_bboxes = dict(_bboxes)
                frame_acct.mark("hud_dirty")

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
            frame_acct.mark("update_hud")
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
        frame_acct.mark("process_frame")

        # ── ETAP 5G: diagnostic raw 691x691 map A/B (GPU resample vs Pillow) ──
        if map_ab_readback and gpu_map_enabled and last_map_img is not None and last_map_dst is not None:
            ab_w, ab_h = int(last_map_dst[2]), int(last_map_dst[3])
            ab_buf = (c_uint8 * (ab_w * ab_h * 4))()
            if native_dll.telem_amd_get_map_resample(h_context, ab_buf, ab_w * 4):
                gpu_map_ab = np.asarray(
                    Image.frombuffer("RGBA", (ab_w, ab_h), ab_buf, "raw", "RGBA", 0, 1),
                    dtype=np.int16,
                )
                cpu_map_ab = np.asarray(
                    last_map_img.resize((ab_w, ab_h), Image.Resampling.LANCZOS),
                    dtype=np.int16,
                )
                diff_ab = np.abs(gpu_map_ab - cpu_map_ab)
                map_ab_results["mae"].append(float(diff_ab.mean()))
                map_ab_results["max"].append(int(diff_ab.max()))
                for key, threshold in (("n>1", 1), ("n>2", 2), ("n>4", 4), ("n>8", 8), ("n>16", 16)):
                    map_ab_results[key].append(float((diff_ab > threshold).mean()))
                if frame_idx in (30, 300, 900):
                    Image.fromarray(gpu_map_ab.astype(np.uint8), "RGBA").save(
                        f"Raporty/AMD_ETAP5G/map_gpu_{map_filter_name.lower()}_frame_{frame_idx}.png")
                    Image.fromarray(cpu_map_ab.astype(np.uint8), "RGBA").save(
                        f"Raporty/AMD_ETAP5G/map_cpu_ref_frame_{frame_idx}.png")
                    ampl = np.clip(diff_ab.max(axis=2).astype(np.float32) * 8.0, 0, 255).astype(np.uint8)
                    Image.fromarray(ampl, "L").save(
                        f"Raporty/AMD_ETAP5G/map_diff_{map_filter_name.lower()}_frame_{frame_idx}.png")

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

        # ── ETAP 5O: per-frame AMF queue diagnostics (lightweight) ─────
        if amf_diag_enabled:
            _dsu = c_uint64(0); _dvp = c_uint64(0); _dsu2 = c_uint64(0); _dre = c_uint64(0)
            native_dll.telem_amd_get_stats(
                h_context, byref(_dsu), byref(_dvp), byref(_dsu2), byref(_dre))
            _hud = c_uint64(0); _vid = c_uint64(0); _if2 = c_uint64(0)
            _rt2 = c_uint64(0); _dr2 = c_uint64(0); _ig2 = c_uint64(0)
            native_dll.telem_amd_get_extended_stats(
                h_context, byref(_hud), byref(_vid), byref(_if2), byref(_rt2),
                byref(_dr2), byref(_ig2))
            amf_diag_samples.append((
                frame_idx, time.perf_counter(), int(_dsu2.value), int(_dre.value),
                int(_if2.value), int(_rt2.value)))

        # ETAP 5J / 5K: per-frame native GPU chart blend submit time.
        if gpu_chart_keys:
            _ch_stats = [c_uint64(0) for _ in range(8)]
            _ch_blend = c_double(0.0)
            _ch_clear = c_double(0.0)
            native_dll.telem_amd_get_chart_stats(
                h_context,
                byref(_ch_stats[0]), byref(_ch_stats[1]), byref(_ch_stats[2]),
                byref(_ch_blend), byref(_ch_clear), byref(_ch_stats[3]),
                byref(_ch_stats[4]), byref(_ch_stats[5]), byref(_ch_stats[6]),
                byref(_ch_stats[7]),
            )
            timing_samples["GPU chart blend submit"].append(float(_ch_blend.value))

            # ── ETAP 5J: diagnostic chart A/B — read back the GPU-blended
            # chart region from the HUD canvas and compare with the exact CPU
            # chart RGBA it was built from (expected: exact, since the chart
            # blends over a freshly-cleared transparent bbox).  Runs every
            # frame when enabled (diagnostic-only, never in production). ────
            if chart_ab_readback:
                for chart_key in gpu_chart_keys:
                    cap = gpu_capture.get(chart_key)
                    if cap is None:
                        continue
                    bx, by, bw, bh = cap["bbox"]
                    if cap.get("split"):
                        # GPU_SPLIT: the CPU reference chart is the exact GPU
                        # assembly — static + cursor/value tiles replaced into
                        # their regions (what the native replace mode writes).
                        ref = np.asarray(cap["static"], dtype=np.uint8).copy()
                        ct = cap["cursor_tile"]
                        if ct is not None:
                            cl = cap["cursor_local"]
                            ref[cl[1]:cl[1] + ct.height,
                                cl[0]:cl[0] + ct.width] = np.asarray(ct, dtype=np.uint8)
                        vt = cap["value_tile"]
                        if vt is not None:
                            vl = cap["value_local"]
                            ref[vl[1]:vl[1] + vt.height,
                                vl[0]:vl[0] + vt.width] = np.asarray(vt, dtype=np.uint8)
                        cpu_chart_ab = ref.astype(np.int16)
                    else:
                        chart_img = cap.get("image")
                        if chart_img is None:
                            continue
                        cpu_chart_ab = np.asarray(chart_img, dtype=np.int16)
                    ab_buf = (c_uint8 * (bw * bh * 4))()
                    if native_dll.telem_amd_get_hud_region_readback(
                        h_context, bx, by, bw, bh, ab_buf, bw * 4,
                    ):
                        gpu_chart_ab = np.asarray(
                            Image.frombuffer("RGBA", (bw, bh), ab_buf, "raw", "RGBA", 0, 1),
                            dtype=np.int16,
                        )
                        diff_ab = np.abs(gpu_chart_ab - cpu_chart_ab)
                        res = chart_ab_results[chart_key]
                        res["mae"].append(float(diff_ab.mean()))
                        res["max"].append(int(diff_ab.max()))
                        for key2, threshold in (("n>1", 1), ("n>2", 2), ("n>4", 4), ("n>8", 8), ("n>16", 16)):
                            res[key2].append(float((diff_ab > threshold).mean()))
                        if frame_idx == 30:
                            Image.fromarray(gpu_chart_ab.astype(np.uint8), "RGBA").save(
                                f"Raporty/AMD_ETAP5G/chart_gpu_{chart_key}_frame30.png")
                            Image.fromarray(cpu_chart_ab.astype(np.uint8), "RGBA").save(
                                f"Raporty/AMD_ETAP5G/chart_cpu_ref_{chart_key}_frame30.png")
                            ampl = np.clip(diff_ab.max(axis=2).astype(np.float32) * 8.0, 0, 255).astype(np.uint8)
                            Image.fromarray(ampl, "L").save(
                                f"Raporty/AMD_ETAP5G/chart_diff_{chart_key}_frame30.png")

        # ETAP 5L: per-frame native GPU gauge blend submit time.
        if gauge_gpu_active:
            _g_up = c_uint64(0)
            _g_bytes = c_uint64(0)
            _g_blend = c_double(0.0)
            _g_clear = c_double(0.0)
            _g_creates = c_uint64(0)
            native_dll.telem_amd_get_gauge_stats(
                h_context,
                byref(_g_up), byref(_g_bytes), byref(_g_blend), byref(_g_clear),
                byref(_g_creates),
            )
            timing_samples["GPU gauge blend submit"].append(float(_g_blend.value))

            # ── ETAP 5L: diagnostic gauge A/B — read back the GPU-blended
            # gauge bbox from the HUD canvas and compare with the CPU_REFERENCE
            # result (raw gauge RGBA with dirty zeros dropped, i.e. Pillow
            # alpha_composite).  Never on the production path. ────────────
            if gauge_ab_readback:
                if gauge_ab_bbox is not None and gauge_ab_img is not None:
                    gx, gy, gw, gh = gauge_ab_bbox
                    ab_buf = (c_uint8 * (gw * gh * 4))()
                    if native_dll.telem_amd_get_hud_region_readback(
                        h_context, gx, gy, gw, gh, ab_buf, gw * 4,
                    ):
                        gpu_gauge_ab = np.asarray(
                            Image.frombuffer("RGBA", (gw, gh), ab_buf,
                                             "raw", "RGBA", 0, 1),
                            dtype=np.int16,
                        )
                        raw = np.asarray(gauge_ab_img, dtype=np.int16)
                        # CPU_REFERENCE result: Pillow alpha_composite drops
                        # RGB where alpha==0 (dirty zeros -> transparent).
                        cpu_gauge_ab = raw.copy()
                        cpu_gauge_ab[cpu_gauge_ab[..., 3] == 0, 0:3] = 0
                        diff = np.abs(gpu_gauge_ab - cpu_gauge_ab)
                        dmax = diff.max(axis=2)
                        gauge_ab_results["mae"].append(float(diff.mean()))
                        gauge_ab_results["max"].append(int(diff.max()))
                        gauge_ab_results["n>0"].append(int((dmax > 0).sum()))
                        for key2, thr in (("n>1", 1), ("n>2", 2), ("n>4", 4), ("n>8", 8)):
                            gauge_ab_results[key2].append(int((dmax > thr).sum()))
                        # dirty zeros / partial alpha in the raw gauge input.
                        dz = int(((raw[..., 3] == 0) & (raw[..., 0:3].max(axis=2) != 0)).sum())
                        pa = int(((raw[..., 3] > 0) & (raw[..., 3] < 255)).sum())
                        gauge_ab_results["dirty_zeros"].append(dz)
                        gauge_ab_results["partial_alpha"].append(pa)
                        if frame_idx in (0, 30, 300, 600, 900, 1130):
                            outdir = Path("Raporty") / "AMD_ETAP5G"
                            outdir.mkdir(parents=True, exist_ok=True)
                            Image.fromarray(gpu_gauge_ab.astype(np.uint8), "RGBA").save(
                                str(outdir / f"l5_gauge_gpu_{frame_idx}.png"))
                            Image.fromarray(cpu_gauge_ab.astype(np.uint8), "RGBA").save(
                                str(outdir / f"l5_gauge_cpu_{frame_idx}.png"))
                            ampl = np.clip(dmax.astype(np.float32) * 16, 0, 255).astype(np.uint8)
                            Image.fromarray(ampl, "L").save(
                                str(outdir / f"l5_gauge_diff_{frame_idx}.png"))
        frame_acct.mark("native_timings")

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
        frame_acct.mark("progress")
        frame_acct.end_frame()
        frame_idx += 1

    # ── ETAP 5P: dump per-frame accounting trace + summary ─────────────
    if fa_enabled:
        etap5p = _frame_accounting_summary(frame_acct)
        if frame_acct.trace:
            _fa_path = Path(output_file_str + ".frame_accounting.json")
            _fa_payload = {
                "summary": etap5p,
                "gc_pauses": frame_acct.gc_pauses,
                "trace": frame_acct.trace,
            }
            try:
                _fa_path.write_text(json.dumps(_fa_payload, indent=1), encoding="utf-8")
                print(f"[AMD NATIVE D3D11] frame accounting trace: {_fa_path}", flush=True)
            except Exception as _e:
                print(f"[AMD NATIVE D3D11] WARNING: frame accounting write failed: {_e}", flush=True)
        print("[ETAP 5P FRAME ACCOUNTING]", flush=True)
        print(f"  frame_total med={etap5p['frame_total_ms']['median']:.3f} ms "
              f"p95={etap5p['frame_total_ms']['p95']:.3f} p99={etap5p['frame_total_ms']['p99']:.3f}",
              flush=True)
        print(f"  measured sum med={etap5p['measured_sum_median_ms']:.3f} ms "
              f"unaccounted med={etap5p['unaccounted_ms']['median']:.3f} ms "
              f"({etap5p['unaccounted_ms']['pct_of_frame']:.1f}%) "
              f"accounted={etap5p['accounted_pct']:.1f}%", flush=True)
        print(f"  GC: collections={etap5p['gc']['collections']} "
              f"total_pause={etap5p['gc']['total_pause_ms']:.1f} ms "
              f"max_pause={etap5p['gc']['max_pause_ms']:.2f} ms", flush=True)
        top = sorted(etap5p["stages"].items(), key=lambda kv: -kv[1]["median_ms"])[:10]
        for i, (name, s) in enumerate(top, 1):
            print(f"  TOP{i:2d} {name:20s} med={s['median_ms']:7.3f} p95={s['p95_ms']:7.3f} "
                  f"{s['median_ms'] / etap5p['frame_total_ms']['median'] * 100:5.1f}%", flush=True)
    else:
        etap5p = {"enabled": False}

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
    if amf_diag_enabled:
        _ds0 = c_uint64(0); _vp0 = c_uint64(0); _su0 = c_uint64(0); _re0 = c_uint64(0)
        native_dll.telem_amd_get_stats(
            h_context, byref(_ds0), byref(_vp0), byref(_su0), byref(_re0))
        amf_preflush_submitted = int(_su0.value)
        amf_preflush_received = int(_re0.value)
    _drain_t0 = time.perf_counter()
    flush_ok = native_dll.telem_amd_flush(h_context)
    amf_drain_ms = (time.perf_counter() - _drain_t0) * 1000.0
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

    # ── ETAP 5O: AMF queue / cadence / drain summary ───────────────────
    etapa5o = {
        "amf_mode": amf_mode,
        "amf_diag": amf_diag_enabled,
        "submitted_total": int(c_sub.value),
        "output_total": int(c_rec.value),
        "input_full_total": int(c_input_full.value),
        "retry_total": int(c_retries.value),
        "preflush_submitted": amf_preflush_submitted,
        "preflush_received": amf_preflush_received,
        "outstanding_at_final_submit": max(0, amf_preflush_submitted - amf_preflush_received),
        "drain_ms": amf_drain_ms,
        "frames_drained_in_flush": max(0, int(c_rec.value) - amf_preflush_received),
        "queue": None,
        "cadence": None,
    }
    if amf_diag_enabled and amf_diag_samples:
        outs = [max(0, s[2] - s[3]) for s in amf_diag_samples]
        def _pct(v, p):
            x = sorted(v); return x[min(len(x) - 1, int(len(x) * p))]
        half = len(outs) // 2
        if half >= 4:
            first = sum(outs[:half]) / half
            second = sum(outs[half:]) / max(1, len(outs) - half)
            trend = ("GROWS" if second > first + 0.5
                     else ("SHRINKS" if second < first - 0.5 else "STABLE"))
        else:
            trend = "STABLE"
        o_times = [
            s[1] for i, s in enumerate(amf_diag_samples)
            if i == 0 or s[3] > amf_diag_samples[i - 1][3]
        ]
        intervals = [o_times[i] - o_times[i - 1] for i in range(1, len(o_times))] or [0.0]
        med_int = _pct(intervals, 0.5)
        etapa5o["queue"] = {
            "avg": sum(outs) / len(outs),
            "median": _pct(outs, 0.5), "p95": _pct(outs, 0.95),
            "p99": _pct(outs, 0.99), "max": max(outs), "trend": trend,
        }
        etapa5o["cadence"] = {
            "n_output_events": len(o_times),
            "median_interval_ms": med_int * 1000.0,
            "p95_interval_ms": _pct(intervals, 0.95) * 1000.0,
            "equivalent_fps": (1.0 / med_int) if med_int > 0 else 0.0,
        }
        print("[ETAP 5O AMF QUEUE]", flush=True)
        print(f"  outstanding: avg={etapa5o['queue']['avg']:.2f} "
              f"med={etapa5o['queue']['median']} p95={etapa5o['queue']['p95']} "
              f"p99={etapa5o['queue']['p99']} max={etapa5o['queue']['max']} "
              f"trend={trend}", flush=True)
        print(f"  output cadence: med={etapa5o['cadence']['median_interval_ms']:.2f} ms "
              f"p95={etapa5o['cadence']['p95_interval_ms']:.2f} ms "
              f"equivFPS={etapa5o['cadence']['equivalent_fps']:.2f}", flush=True)
    print(f"  AMF final drain: outstanding_at_final_submit="
          f"{etapa5o['outstanding_at_final_submit']} drain={amf_drain_ms:.0f} ms "
          f"frames_drained={etapa5o['frames_drained_in_flush']}", flush=True)

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
    print(f"  GPU chart path:   {requested_chart_path} ({gpu_chart_reason})", flush=True)
    print(f"  Chart GPU frames: CAD={chart_gpu_frames.get('fit_cadence_text', 0)} HR={chart_gpu_frames.get('fit_heart_rate_text', 0)}", flush=True)
    if gpu_charts_split:
        print(
            f"  Chart static uploads: {chart_static_uploads} "
            f"({chart_static_bytes_total / (1024.0 * 1024.0):.3f} MiB total)",
            flush=True,
        )
        print(
            f"  Chart dynamic uploads: {chart_dynamic_uploads} "
            f"({chart_dynamic_bytes_total / (1024.0 * 1024.0):.4f} MiB total, "
            f"{chart_dynamic_bytes_total / max(1, chart_split_frames) / (1024.0 * 1024.0):.4f} MiB/frame)",
            flush=True,
        )
        print(
            f"  Chart full 1160x511 tobytes: {chart_full_tobytes_total} total "
            f"(static-only, {chart_full_tobytes_total - len(chart_static_uploaded)} per-frame)",
            flush=True,
        )
    else:
        print(f"  Chart upload MiB:{chart_uploaded_bytes_total / (1024.0 * 1024.0):9.2f} total", flush=True)
    print(f"  GPU gauge path:   {requested_gauge_path} ({gauge_gpu_reason})", flush=True)
    print(f"  Gauge GPU frames: {gauge_gpu_frames}", flush=True)
    print(
        f"  Gauge upload MiB: {gauge_uploaded_bytes_total / (1024.0 * 1024.0):.4f} total, "
        f"{gauge_uploaded_bytes_total / max(1, gauge_gpu_frames) / (1024.0 * 1024.0):.4f} MiB/frame",
        flush=True,
    )
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
    if amf_mode in ("SUBMIT_NO_MUX", "BYPASS"):
        # ETAP 5O/5U diagnostic: encode+query done (SUBMIT_NO_MUX) or frontend
        # only with no encoder (BYPASS) — skip mux / file I/O.
        muxed_frames = int(c_rec.value)
        audio_present = False
        final_probe = None
        print(
            "[AMD NATIVE D3D11] " + ("SUBMIT_NO_MUX" if amf_mode == "SUBMIT_NO_MUX"
                                     else "AMF BYPASS")
            + ": encoded packets counted / frontend only, mux skipped "
            f"(h265 temp = {temp_h265})",
            flush=True,
        )
    else:
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

        final_probe = _probe_video_summary(ffmpeg_exe, output_file_str)
        muxed_frames = _stream_frame_count(final_probe, "video")
        audio_present = any(
            stream.get("codec_type") == "audio" for stream in final_probe.get("streams", [])
        )
    end_to_end_elapsed = time.perf_counter() - end_to_end_start
    if amf_mode == "BYPASS":
        # ETAP 5U: frontend-only equivalent FPS (no encoder) — use VP frames.
        true_fps = c_vp.value / end_to_end_elapsed if end_to_end_elapsed > 0 else 0.0
    else:
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
            "cadence_gpu": chart_gpu_frames.get("fit_cadence_text", 0),
            "hr_gpu": chart_gpu_frames.get("fit_heart_rate_text", 0),
            "map_gpu": map_gpu_frames,
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
            "hud_buffer_mode": hud_buffer_mode,
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
        "etap5g": {
            "map_path": "GPU" if gpu_map_enabled else "CPU_REFERENCE",
            "map_path_requested": requested_map_path,
            "map_path_safe_reason": map_gpu_reason,
            "map_filter": map_filter_name,
            "map_filter_index": map_filter,
            "map_gpu_frames": map_gpu_frames,
            "map_upload_frames": len(map_upload_times),
            "map_upload_bytes_total": map_uploaded_bytes_total,
            "map_upload_mib_per_frame": (
                (map_uploaded_bytes_total / max(1, map_gpu_frames)) / (1024.0 * 1024.0)
                if map_gpu_frames else 0.0
            ),
            "map_cpu_upload_ms": _value_summary(map_upload_times) if map_upload_times else None,
            "map_ab_readback": map_ab_readback,
            "map_ab": (
                {key: _value_summary(values) for key, values in map_ab_results.items()}
                if map_ab_readback and map_ab_results["mae"] else None
            ),
        },
        "etap5j": {
            "chart_path": requested_chart_path,
            "chart_path_requested": requested_chart_path,
            "chart_path_safe_reason": gpu_chart_reason,
            "active_gpu_charts": sorted(gpu_chart_keys),
            "chart_gpu_frames_cadence": chart_gpu_frames.get("fit_cadence_text", 0),
            "chart_gpu_frames_hr": chart_gpu_frames.get("fit_heart_rate_text", 0),
            "chart_upload_bytes_total": chart_uploaded_bytes_total,
            "chart_upload_mib_per_frame": (
                chart_uploaded_bytes_total / max(1, hud_frames) / (1024.0 * 1024.0)
                if hud_frames else 0.0
            ),
            "chart_gpu_to_cpu_readback": 0,
            "chart_persistent_textures": len(gpu_chart_keys),
            "chart_ab_readback": chart_ab_readback,
            "chart_ab": (
                {key: {k2: _value_summary(v2) for k2, v2 in res.items() if v2}
                 for key, res in chart_ab_results.items() if res["mae"]}
                if chart_ab_readback else None
            ),
        },
        "etap5k": {
            "split": gpu_charts_split,
            "static_uploads": chart_static_uploads,
            "static_bytes_total": chart_static_bytes_total,
            "static_mib_total": chart_static_bytes_total / (1024.0 * 1024.0),
            "dynamic_uploads": chart_dynamic_uploads,
            "dynamic_bytes_total": chart_dynamic_bytes_total,
            "dynamic_mib_per_frame": (
                chart_dynamic_bytes_total / max(1, chart_split_frames) / (1024.0 * 1024.0)
                if chart_split_frames else 0.0
            ),
            "full_tobytes_total": chart_full_tobytes_total,
            "full_tobytes_per_frame": (
                (chart_full_tobytes_total - len(chart_static_uploaded)) / max(1, hud_frames)
                if hud_frames else 0.0
            ),
            "split_frames": chart_split_frames,
            "static_ab": chart_static_ab_results or None,
        },
        "etap5l": {
            "gauge_path": requested_gauge_path,
            "gauge_path_safe_reason": gauge_gpu_reason,
            "gauge_gpu_active": gauge_gpu_active,
            "gauge_gpu_frames": gauge_gpu_frames,
            "gauge_upload_bytes_total": gauge_uploaded_bytes_total,
            "gauge_upload_mib_per_frame": (
                gauge_uploaded_bytes_total / max(1, gauge_gpu_frames) / (1024.0 * 1024.0)
                if gauge_gpu_frames else 0.0
            ),
            "gauge_gpu_to_cpu_readback": 0,
            "gauge_ab_readback": gauge_ab_readback,
            "gauge_ab": (
                {key: _value_summary(values) for key, values in gauge_ab_results.items() if values}
                if gauge_ab_readback and gauge_ab_results["mae"] else None
            ),
        },
        "etap5a": overlay_profiler.summary(),
        "etap5o": etapa5o,
        "etap5p": etap5p if etap5p is not None else {"enabled": fa_enabled},
        "etap5n": {
            "telemetry_mode": telemetry_mode,
            "precomputed": (
                {
                    "frames": telemetry_cache.frames,
                    "build_ms": telemetry_cache.build_ms,
                    "memory_mib": telemetry_cache.memory_bytes / (1024.0 * 1024.0),
                    "structure": telemetry_cache.stats()["structure"],
                    "resolver_calls_per_frame": (
                        telemetry_cache.resolver_calls / max(1, telemetry_cache.frames)
                    ),
                    "interpolation_calls_per_frame": (
                        telemetry_cache.interpolation_calls / max(1, telemetry_cache.frames)
                    ),
                    "gpmf_lookups_per_frame": (
                        telemetry_cache.gpmf_lookups / max(1, telemetry_cache.frames)
                    ),
                }
                if telemetry_cache is not None else None
            ),
        },
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
