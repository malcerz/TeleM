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
import queue
import threading
from dataclasses import dataclass
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

# ── ETAP 8T-B: Asynchronous CPU Producer + Synchronous GPU Consumer Pipeline ──
_END_OF_STREAM = object()

@dataclass
class PreparedFrame:
    frame_idx: int
    sample_time_seconds: float
    curr_dt: Any
    hud_work_enabled: bool
    
    # Timing
    producer_prepare_ms: float
    t_prod_begin: float
    t_prod_end: float
    
    # HUD Below Layer (dirty rects bytearray + bounding boxes)
    native_hud_mode: str
    full_hud_upload: bool
    dirty_rects: list[tuple[int, int, int, int]]
    dirty_rect_slices: list[tuple[int, int, int, int, bytes]] # (x, y, w, h, region_bytes)
    hud_backing_array: Optional[np.ndarray] # only when full_hud_upload=True
    rgba_bytes_reference: Optional[bytes] # only when CPU_REFERENCE mode
    
    # Dynamic Charts
    chart_static_uploads: list[tuple[int, bytes, int, int, int, int, str]] # (slot, bytes, w, h, x, y, chart_key)
    chart_dynamic_tiles: list[tuple[int, int, bytes, int, int, int, int]] # (slot, region_idx, bytes, w, h, x, y)
    
    # Gauge
    gauge_active: bool
    gauge_data: Optional[tuple[bytes, int, int, int, int]] # (bytes, w, h, x, y)
    
    # Above Map Layer
    above_regions: list[tuple[int, int, int, int, bytes]] # (rx, ry, rw, rh, bytes)
    
    # Map
    map_active: bool
    map_data: Optional[tuple[bytes, int, int, tuple[int, int, int, int]]] # (bytes, w, h, dst_rect)
    map_geometry: Optional[tuple[int, int, int, int, int, int]] # (dst_x, dst_y, src_w, src_h, out_w, out_h)
    
    # Diagnostics & Profiling
    timing_samples_producer: dict[str, float]
    intermediate_bytes: int
    persistent_copy_bytes: int
    upload_bytes: int
    rect_count: int
    above_stats: dict[str, Any]
    last_map_img: Optional[Any] = None
    last_map_dst: Optional[Any] = None


_AMD_HUD_MODES = {"CPU_REFERENCE": 0, "GPU_HUD": 1}
_AMD_DECODE_MODES = {
    "GPU_HUD_CPU_DECODE_REFERENCE": 0,
    "CPU_DECODE_REFERENCE": 0,
    "GPU_HUD_D3D11VA": 1,
    "D3D11VA": 1,
}


def _resolve_amd_decode_mode(native_hud_mode: str, requested_decode_mode: str) -> tuple[str, bool]:
    """Keep the CPU reference HUD on the CPU-NV12 path.

    ``telem_amd_update_hud`` performs the reference RGBA->NV12 blend while
    uploading a CPU-decoded frame.  D3D11VA supplies only a GPU surface, so
    the native compositor intentionally disables its GPU HUD in
    ``CPU_REFERENCE`` mode and would otherwise submit an uncomposited base
    surface to AMF.
    """
    use_d3d11va = _AMD_DECODE_MODES[requested_decode_mode] == 1
    if native_hud_mode == "CPU_REFERENCE" and use_d3d11va:
        return "GPU_HUD_CPU_DECODE_REFERENCE", False
    return requested_decode_mode, use_d3d11va
# ETAP 5G — GPU map resize/composite.  CPU_REFERENCE keeps the map in the
# Pillow HUD (unchanged); GPU uploads the 692x692 working map and resizes +
# composites it on the GPU.  Filter: 0=bilinear, 1=bicubic, 2=Lanczos-3.
_AMD_MAP_FILTERS = {"BILINEAR": 0, "BICUBIC": 1, "LANCZOS": 2}
# ETAP 8U-B: Map GPU path mode (0 = DIRECT_AUTO default, 1 = REFERENCE two-pass, 2 = DIRECT_1TO1).
_AMD_MAP_GPU_PATHS = {
    "DIRECT_AUTO": 0,
    "AUTO": 0,
    "DIRECT": 0,
    "REFERENCE": 1,
    "TWO_PASS": 1,
    "DIRECT_1TO1": 2,
    "FORCE_DIRECT": 2,
}

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
    """Return whether the single canonical map can use the ordered GPU path."""
    indicators = layout.get("indicators", {})
    if "track_map" not in indicators or not indicators["track_map"].get("enabled", True):
        return True, "no active track_map"
    map_count = sum(1 for key, cfg in indicators.items()
                    if cfg and cfg.get("enabled", True) and key == "track_map")
    if map_count != 1:
        return False, f"canonical track_map count={map_count}; ordered GPU path requires exactly one"
    return True, "single canonical track_map -> ordered CPU_BELOW_MAP/GPU_MAP/CPU_ABOVE_MAP"


def _ordered_map_layout_parts(layout: dict) -> tuple[dict, dict, list[str]]:
    """Split one map layout while preserving indicator insertion order."""
    below = copy.deepcopy(layout)
    above = copy.deepcopy(layout)
    below_indicators = {}
    above_indicators = {}
    before_map = True
    after_keys: list[str] = []
    for key, cfg in layout.get("indicators", {}).items():
        # compose_overlay renders these before the normal indicator loop even
        # if a legacy JSON preset places them later in the dict.
        if key in {"time_block", "time_display"}:
            below_indicators[key] = copy.deepcopy(cfg)
            continue
        if key == "track_map":
            before_map = False
            continue
        if before_map:
            below_indicators[key] = copy.deepcopy(cfg)
        else:
            above_indicators[key] = copy.deepcopy(cfg)
            after_keys.append(key)
    below["indicators"] = below_indicators
    above["indicators"] = {
        key: cfg for key, cfg in above_indicators.items()
        if key not in {"time_block", "time_display"}
    }
    # custom_texts are rendered after all indicators by Pillow.
    below["custom_texts"] = []
    above["custom_texts"] = copy.deepcopy(layout.get("custom_texts", []))
    return below, above, after_keys


def _amd_layout_roles(
    layout: dict[str, Any],
    gpu_map_enabled: bool,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any] | None, list[str]]:
    """Return semantic and compositing layouts for the AMD ordered-map path.

    The full user layout remains the source of widget semantics and all
    precomputed telemetry.  Only the compositing layout is partitioned for
    the below-map / map / above-map z-order phases.
    """
    semantic_layout = layout
    compose_layout = layout
    map_above_layout = None
    map_after_keys: list[str] = []
    track_map_cfg = layout.get("indicators", {}).get("track_map")
    if (
        gpu_map_enabled
        and track_map_cfg
        and track_map_cfg.get("enabled", True)
    ):
        compose_layout, map_above_layout, map_after_keys = _ordered_map_layout_parts(layout)
    return semantic_layout, compose_layout, map_above_layout, map_after_keys


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


def _rendered_bbox_union(
    bboxes: dict[str, tuple[int, int, int, int]],
    width: int,
    height: int,
    pad: int = 64,
) -> tuple[int, int, int, int] | None:
    """Build a conservative crop from actually rendered compositor bboxes."""
    valid = [
        tuple(int(v) for v in box)
        for box in bboxes.values()
        if box and int(box[2]) > 0 and int(box[3]) > 0
    ]
    if not valid:
        return None
    left = min(x for x, _y, _w, _h in valid)
    top = min(y for _x, y, _w, _h in valid)
    right = max(x + w for x, _y, w, _h in valid)
    bottom = max(y + h for _x, y, _w, h in valid)
    return _clip_rect((left, top, right - left, bottom - top), width, height, pad)


def _tight_alpha_bbox_from_candidate(
    image: "Image.Image",
    candidate: tuple[int, int, int, int] | None,
) -> tuple[tuple[int, int, int, int] | None, int]:
    """Find the tight global alpha bbox while scanning only *candidate*."""
    if candidate is None:
        return None, 0
    x, y, width, height = candidate
    local = image.crop((x, y, x + width, y + height))
    local_bbox = local.getchannel("A").getbbox()
    if local_bbox is None:
        return None, width * height
    lx, ly, rx, by = local_bbox
    return (x + lx, y + ly, rx - lx, by - ly), width * height


def _cluster_above_bboxes(
    bboxes: dict[str, tuple[int, int, int, int]],
    canvas_w: int,
    canvas_h: int,
    pad: int = 16,
    merge_dist: int = 32,
    max_regions: int = 16,
) -> list[tuple[int, int, int, int]]:
    """Cluster rendered indicator bboxes into a small list of disjoint compact candidate regions."""
    valid_rects: list[tuple[int, int, int, int]] = []
    for box in bboxes.values():
        if not box or int(box[2]) <= 0 or int(box[3]) <= 0:
            continue
        clipped = _clip_rect(box, canvas_w, canvas_h, pad=pad)
        if clipped is not None:
            valid_rects.append(clipped)

    if not valid_rects:
        return []

    # Iterative merge of overlapping or close rectangles (distance <= merge_dist)
    merged = list(valid_rects)
    changed = True
    while changed:
        changed = False
        for i in range(len(merged)):
            for j in range(i + 1, len(merged)):
                r1, r2 = merged[i], merged[j]
                dx = max(0, max(r1[0], r2[0]) - min(r1[0] + r1[2], r2[0] + r2[2]))
                dy = max(0, max(r1[1], r2[1]) - min(r1[1] + r1[3], r2[1] + r2[3]))
                if dx <= merge_dist and dy <= merge_dist:
                    union_box = _rect_union(r1, r2)
                    merged.pop(j)
                    merged.pop(i)
                    merged.append(union_box)
                    changed = True
                    break
            if changed:
                break

    # If count > max_regions, merge closest pairs until <= max_regions
    while len(merged) > max_regions:
        best_pair = None
        min_dist_sq = float('inf')
        for i in range(len(merged)):
            for j in range(i + 1, len(merged)):
                r1, r2 = merged[i], merged[j]
                c1 = (r1[0] + r1[2] / 2.0, r1[1] + r1[3] / 2.0)
                c2 = (r2[0] + r2[2] / 2.0, r2[1] + r2[3] / 2.0)
                dist_sq = (c1[0] - c2[0]) ** 2 + (c1[1] - c2[1]) ** 2
                if dist_sq < min_dist_sq:
                    min_dist_sq = dist_sq
                    best_pair = (i, j)
        if best_pair is None:
            break
        i, j = best_pair
        union_box = _rect_union(merged[i], merged[j])
        merged.pop(j)
        merged.pop(i)
        merged.append(union_box)

    return merged


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
    on_render_progress: Optional[Callable[[int, int, float, float, Optional[dict]], None]] = None,
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
    
    # ETAP 8P-A: Precise wall-clock milestone timers
    t_export_start = time.perf_counter()
    t_precompute_begin = 0.0
    t_precompute_end = 0.0
    t_first_frame_begin = 0.0
    t_first_frame_encoded = 0.0
    t_video_render_end = 0.0
    t_mux_begin = 0.0
    t_mux_end = 0.0

    diagnostics_enabled = _env_flag("AMD_NATIVE_DIAGNOSTICS", False)
    profiling_enabled = diagnostics_enabled or _env_flag("AMD_NATIVE_PROFILING", False) or _env_flag("AMD_GPU_TIMESTAMP_PROFILE", False)
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
    requested_native_decode_mode = native_decode_mode
    native_decode_mode, use_d3d11va = _resolve_amd_decode_mode(
        native_hud_mode, native_decode_mode
    )
    if native_decode_mode != requested_native_decode_mode:
        print(
            "[AMD NATIVE D3D11] CPU_REFERENCE HUD requires CPU-NV12 reference "
            "decode; overriding GPU_HUD_D3D11VA to GPU_HUD_CPU_DECODE_REFERENCE.",
            flush=True,
        )
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
    cpu_reference_hud = native_hud_mode == "CPU_REFERENCE"

    # ── ETAP 5G: GPU map resize/composite ───────────────────────────────
    # CPU_REFERENCE keeps the map in the Pillow HUD (unchanged).  GPU uploads
    # the 692x692 working map and resizes + composites it on the GPU.  The
    # z-order guard falls back to CPU_REFERENCE for unsafe layouts.
    # ETAP (GUI integration): production default is GPU (approved 5G+ path).
    requested_map_path = os.environ.get("AMD_MAP_PATH", "GPU").strip().upper()
    if requested_map_path not in {"CPU_REFERENCE", "GPU"}:
        print("[AMD NATIVE D3D11] ERROR: AMD_MAP_PATH must be CPU_REFERENCE or GPU.", flush=True)
        return False
    if cpu_reference_hud:
        requested_map_path = "CPU_REFERENCE"
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
    # ETAP 8U-B: Map GPU path mode (DIRECT_AUTO, REFERENCE, DIRECT_1TO1).
    map_gpu_path_name = os.environ.get("AMD_MAP_GPU_PATH", "DIRECT_AUTO").strip().upper()
    if map_gpu_path_name not in _AMD_MAP_GPU_PATHS:
        map_gpu_path_name = "DIRECT_AUTO"
    map_gpu_path_val = _AMD_MAP_GPU_PATHS[map_gpu_path_name]
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
            f"[AMD NATIVE D3D11] GPU map filter: {map_filter_name} ({map_filter}) | GPU map path: {map_gpu_path_name} ({map_gpu_path_val})",
            flush=True,
        )

    # ETAP 5G: in GPU map mode the track_map widget leaves the Pillow HUD; the
    # CPU still renders its 692x692 working image, which is uploaded and
    # resized/composited on the GPU.  Everything else keeps the 5E path.
    semantic_layout, compose_layout, map_above_layout, map_after_keys = _amd_layout_roles(
        layout, gpu_map_enabled,
    )
    if map_above_layout is not None:
        print(
            "[AMD NATIVE D3D11] AMD_MAP_ORDER: "
            "CPU_BELOW_MAP -> GPU_MAP -> CPU_ABOVE_MAP "
            f"(after={map_after_keys or 'empty'})",
            flush=True,
        )

    # ── ETAP 5J: GPU chart compositing ─────────────────────────────────
    # CPU_REFERENCE keeps both charts in the Pillow HUD (unchanged).  GPU
    # renders the exact same chart RGBA on the CPU but blends it into the GPU
    # HUD canvas instead.  The actual safe-chart set is computed at runtime
    # from a probe frame by the z-order guard (with automatic fallback for any
    # chart that overlaps another widget / the GPU map).
    # ETAP (GUI integration): production default is GPU_SPLIT (approved 5J/5K
    # path); unsafe charts still fall back to CPU_REFERENCE.
    requested_chart_path = os.environ.get("AMD_CHART_PATH", "GPU_SPLIT").strip().upper()
    if requested_chart_path not in _AMD_CHART_PATHS:
        print("[AMD NATIVE D3D11] ERROR: AMD_CHART_PATH must be CPU_REFERENCE, GPU or GPU_SPLIT.", flush=True)
        return False
    if cpu_reference_hud:
        requested_chart_path = "CPU_REFERENCE"
    gpu_charts_requested = requested_chart_path in ("GPU", "GPU_SPLIT")
    gpu_charts_split = requested_chart_path == "GPU_SPLIT"
    chart_mode_value = _AMD_CHART_PATHS[requested_chart_path]
    print(f"[AMD NATIVE D3D11] AMD_CHART_PATH: {requested_chart_path}", flush=True)

    # ── ETAP 5L: GPU gauge compositing ─────────────────────────────────
    # ETAP (GUI integration): production default is GPU (approved 5L path);
    # unsafe layouts fall back to CPU_REFERENCE.
    requested_gauge_path = os.environ.get("AMD_GAUGE_PATH", "GPU").strip().upper()
    if requested_gauge_path not in _AMD_GAUGE_PATHS:
        print("[AMD NATIVE D3D11] ERROR: AMD_GAUGE_PATH must be CPU_REFERENCE or GPU.", flush=True)
        return False
    if cpu_reference_hud:
        requested_gauge_path = "CPU_REFERENCE"
    gauge_gpu_requested = requested_gauge_path == "GPU"
    print(f"[AMD NATIVE D3D11] AMD_GAUGE_PATH: {requested_gauge_path}", flush=True)

    # ── ETAP 8O: telemetry mode (precomputed frame cache is production default) ──
    telemetry_mode = os.environ.get("AMD_TELEMETRY_MODE", "PRECOMPUTED").strip().upper()
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

    native_dll.telem_amd_set_map_gpu_path.restype = c_int
    native_dll.telem_amd_set_map_gpu_path.argtypes = [c_void_p, c_int]

    native_dll.telem_amd_get_map_gpu_path_used.restype = c_int
    native_dll.telem_amd_get_map_gpu_path_used.argtypes = [c_void_p]

    native_dll.telem_amd_set_map_geometry.restype = c_int
    native_dll.telem_amd_set_map_geometry.argtypes = [
        c_void_p, c_uint, c_uint, c_uint, c_uint, c_uint, c_uint,
    ]

    native_dll.telem_amd_update_map.restype = c_int
    native_dll.telem_amd_update_map.argtypes = [
        c_void_p, ctypes.c_char_p, c_uint, c_uint, c_uint,
        POINTER(c_uint64), POINTER(c_int),
    ]

    native_dll.telem_amd_set_above_map_mode.restype = c_int
    native_dll.telem_amd_set_above_map_mode.argtypes = [c_void_p, c_int]
    native_dll.telem_amd_update_above_regions_count.restype = c_int
    native_dll.telem_amd_update_above_regions_count.argtypes = [c_void_p, c_uint]
    native_dll.telem_amd_update_above_region.restype = c_int
    native_dll.telem_amd_update_above_region.argtypes = [
        c_void_p, c_uint, POINTER(c_uint8), c_uint, c_uint, c_uint,
        c_uint, c_uint,
    ]
    native_dll.telem_amd_update_above_map.restype = c_int
    native_dll.telem_amd_update_above_map.argtypes = [
        c_void_p, POINTER(c_uint8), c_uint, c_uint, c_uint,
        c_uint, c_uint, c_int,
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
            layout=semantic_layout,
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
    # ── REAL GUI production configuration summary (integration fix) ───────
    print("[AMD NATIVE D3D11] === REAL PRODUCTION CONFIG ===", flush=True)
    print(f"  AMD_MAP_PATH effective:   {'GPU' if gpu_map_enabled else 'CPU_REFERENCE'}", flush=True)
    print(f"  AMD_CHART_PATH effective: {requested_chart_path if gpu_charts_requested else 'CPU_REFERENCE'}", flush=True)
    print(f"  AMD_GAUGE_PATH effective: {'GPU' if gauge_gpu_requested else 'CPU_REFERENCE'}", flush=True)
    print(f"  AMD_COMPOSE_5Q:           {os.environ.get('AMD_COMPOSE_5Q', 'OPTIMIZED').strip().upper()}", flush=True)
    print(f"  AMD_NATIVE_DECODE_MODE:   {native_decode_mode}", flush=True)
    print(f"  AMD_NATIVE_HUD_MODE:      {native_hud_mode}", flush=True)
    print(f"  AMD_NATIVE_HUD_UPLOAD:    {hud_upload_mode}", flush=True)
    fused_mode = os.environ.get('AMD_FUSED_COMPOSITOR', '1').strip()
    print(f"  AMD_NV12_COMPOSITOR:      {'FUSED (production single-range)' if fused_mode == '1' else 'LEGACY_SEPARATE (diagnostic)'}", flush=True)
    print(f"  AMD_NORMALIZE_PASSES:     {0 if fused_mode == '1' else os.environ.get('AMD_NORMALIZE_PASSES', '1')}", flush=True)
    print(f"  AMD_VP_POOL_SIZE:         {os.environ.get('AMD_VP_POOL_SIZE', '8 (native default)')}", flush=True)
    try:
        from src.video_helpers import ffprobe_resolution
        src_w_h = ffprobe_resolution(input_file_str, ffmpeg_exe.replace("ffmpeg.exe", "ffprobe.exe") if ffmpeg_exe else "ffprobe")
        src_w_log = src_w_h[0] if src_w_h else video_width
        src_h_log = src_w_h[1] if src_w_h else video_height
    except Exception:
        src_w_log, src_h_log = video_width, video_height
    print(f"[AMD NATIVE D3D11] SOURCE VIDEO:      {src_w_log}x{src_h_log}", flush=True)
    print(f"[AMD NATIVE D3D11] REQUESTED OUTPUT:  {video_width}x{video_height}", flush=True)
    print(f"[AMD NATIVE D3D11] VP OUTPUT:          {video_width}x{video_height}", flush=True)
    print(f"[AMD NATIVE D3D11] AMF OUTPUT:         {video_width}x{video_height}", flush=True)
    print("[AMD NATIVE D3D11] ===================================", flush=True)
    proc_dec: subprocess.Popen | None = None
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

    def _cleanup_native_resources() -> None:
        """P1-A FIX: Idempotent cleanup of native D3D11 context and decoder process."""
        nonlocal h_context, proc_dec
        if proc_dec is not None:
            if proc_dec.poll() is None:
                try:
                    proc_dec.kill()
                except Exception:
                    pass
            try:
                proc_dec.wait(timeout=2.0)
            except Exception:
                pass
            proc_dec = None
        if h_context is not None:
            ctx_to_close = h_context
            h_context = None
            try:
                native_dll.telem_amd_close(ctx_to_close)
            except Exception as _ce:
                print(f"[AMD NATIVE D3D11] telem_amd_close error: {_ce}", flush=True)

    if not native_dll.telem_amd_set_diagnostics(h_context, 1 if diagnostics_enabled else 0):
        print("[AMD NATIVE D3D11] ERROR: failed to configure diagnostic mode.", flush=True)
        _cleanup_native_resources()
        return False

    if not native_dll.telem_amd_set_profiling(h_context, 1 if profiling_enabled else 0):
        print("[AMD NATIVE D3D11] ERROR: failed to configure profiling mode.", flush=True)
        _cleanup_native_resources()
        return False

    if not native_dll.telem_amd_set_hud_enabled(h_context, 1 if hud_work_enabled else 0):
        print("[AMD NATIVE D3D11] ERROR: failed to configure HUD mode.", flush=True)
        _cleanup_native_resources()
        return False

    if not native_dll.telem_amd_set_hud_mode(h_context, _AMD_HUD_MODES[native_hud_mode]):
        print("[AMD NATIVE D3D11] ERROR: failed to configure HUD compositor.", flush=True)
        _cleanup_native_resources()
        return False

    # ── ETAP 5G: GPU map resize/composite ───────────────────────────────
    if not native_dll.telem_amd_set_map_mode(h_context, 1 if gpu_map_enabled else 0):
        print("[AMD NATIVE D3D11] ERROR: failed to configure GPU map mode.", flush=True)
        _cleanup_native_resources()
        return False
    if not native_dll.telem_amd_set_above_map_mode(h_context, 1 if gpu_map_enabled else 0):
        print("[AMD NATIVE D3D11] ERROR: failed to configure ordered map-above mode.", flush=True)
        _cleanup_native_resources()
        return False
    if gpu_map_enabled:
        if not native_dll.telem_amd_set_map_filter(h_context, map_filter):
            print("[AMD NATIVE D3D11] ERROR: failed to configure GPU map filter.", flush=True)
            _cleanup_native_resources()
            return False
        if not native_dll.telem_amd_set_map_gpu_path(h_context, map_gpu_path_val):
            print("[AMD NATIVE D3D11] ERROR: failed to configure GPU map path.", flush=True)
            _cleanup_native_resources()
            return False

    # ── ETAP 5J / 5K: GPU chart compositing (0 = CPU_REFERENCE, 1 = GPU,
    # 2 = GPU_SPLIT) ───────────────────────────────────────────────────
    if not native_dll.telem_amd_set_chart_mode(h_context, chart_mode_value):
        print("[AMD NATIVE D3D11] ERROR: failed to configure GPU chart mode.", flush=True)
        _cleanup_native_resources()
        return False

    # ── ETAP 5L: GPU gauge compositing (1 = GPU, 0 = CPU_REFERENCE) ────
    if not native_dll.telem_amd_set_gauge_mode(h_context, 1 if gauge_gpu_requested else 0):
        print("[AMD NATIVE D3D11] ERROR: failed to configure GPU gauge mode.", flush=True)
        _cleanup_native_resources()
        return False

    if not native_dll.telem_amd_set_source_rotation(h_context, source_rotation):
        print("[AMD NATIVE D3D11] ERROR: failed to configure source rotation.", flush=True)
        _cleanup_native_resources()
        return False

    if not native_dll.telem_amd_set_decode_mode(
        h_context, _AMD_DECODE_MODES[native_decode_mode]
    ):
        print(
            f"[AMD NATIVE D3D11] ERROR: decode mode {native_decode_mode} unavailable; "
            "no implicit per-frame fallback is allowed.",
            flush=True,
        )
        _cleanup_native_resources()
        return False

    # ── ETAP 5U: AMF mode (0=ENCODE production, 1=BYPASS frontend-only). ──
    if amf_mode == "BYPASS":
        if not native_dll.telem_amd_set_amf_mode(h_context, 1):
            print("[AMD NATIVE D3D11] ERROR: failed to configure AMF BYPASS mode.", flush=True)
            _cleanup_native_resources()
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
        "telemetry_target_dt": [],
        "telemetry_cache_lookup": [],
        "telemetry_frame_payload": [],
        "telemetry_shared_objects": [],
        "telemetry_other": [],
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
        # ETAP 8B diagnostic decomposition of the former chart_upload bucket.
        "chart_plan": [],
        "chart_rgba_conversion": [],
        "chart_upload_call": [],
        "chart_native_submit": [],
        "chart_gpu_submit": [],
        "chart_other": [],
        "above_compose": [],
        "above_canvas_prepare": [],
        "above_cache_lookup": [],
        "above_cache_hit": [],
        "above_cache_miss_render": [],
        "above_cached_paste": [],
        "above_compose_total": [],
        "above_bbox_crop": [],
        "above_bbox_tracking": [],
        "above_candidate_crop": [],
        "above_local_alpha_scan": [],
        "above_final_crop": [],
        "above_region_to_bytes": [],
        "above_region_upload": [],
        "above_total": [],
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
    above_map_frames = 0
    above_map_visible_frames = 0
    above_map_uploaded_bytes_total = 0
    above_region_counts_samples: list[int] = []
    above_candidate_pixels_samples: list[int] = []
    above_scanned_pixels_samples: list[int] = []
    above_uploaded_pixels_samples: list[int] = []
    above_uploaded_bytes_samples: list[int] = []
    above_candidate_bbox_samples: list[tuple[int, int, int, int] | None] = []
    above_final_bbox_samples: list[tuple[int, int, int, int] | None] = []
    above_candidate_widths: list[float] = []
    above_candidate_heights: list[float] = []
    above_final_widths: list[float] = []
    above_final_heights: list[float] = []
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
            _cleanup_native_resources()
            return False
    else:
        print("[AMD NATIVE D3D11VA] FFmpeg rawvideo decoder pipe: OFF", flush=True)

    # ── ETAP 5N: precomputed telemetry cache (PRECOMPUTED mode) ─────────
    # Live reference closure (used by REFERENCE mode and as the VFR fallback).
    def _live_frame_data(frame_idx, curr_dt, chart_data):
        return prepare_overlay_frame_data(
            layout=semantic_layout,
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
    t_precompute_begin = time.perf_counter()
    if telemetry_mode == "PRECOMPUTED":
        from src.telemetry_precompute import build_telemetry_cache
        _pre_t0 = time.perf_counter()
        telemetry_cache = build_telemetry_cache(
            layout=semantic_layout,
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
    t_precompute_end = time.perf_counter()

    # Main Frame Processing Loop
    # ── ETAP 8T-B/C: Unified Producer-Consumer Frame Pipeline ──
    pipeline_mode = os.getenv("AMD_CPU_GPU_PIPELINE", "SYNC").upper()
    if pipeline_mode not in ("ASYNC", "SYNC"):
        pipeline_mode = "SYNC"
    print(f"[AMD NATIVE D3D11] AMD_CPU_GPU_PIPELINE={pipeline_mode}", flush=True)

    previous_bboxes_holder = [{}] # Mutable cell for producer
    map_geometry_set_holder = [False]
    last_hud_report_holder = [0.0]
    timeline_trace = [] # First 20 frames trace
    
    # Pre-allocate timing sample containers for producer/consumer
    timing_samples["producer_prepare"] = []
    timing_samples["producer_queue_wait"] = []
    timing_samples["consumer_queue_wait"] = []
    timing_samples["consumer_upload"] = []
    timing_samples["consumer_native_call"] = []
    timing_samples["consumer_packet"] = []
    timing_samples["pipeline_total"] = []

    def _prepare_frame_cpu(idx: int) -> PreparedFrame:
        t_p_start = time.perf_counter()
        sample_time_sec = idx / target_fps
        c_dt = base_dt + timedelta(seconds=sample_time_sec) if base_dt is not None else None
        
        t_samples_p: dict[str, float] = {}
        above_stats_p: dict[str, Any] = {}
        
        if not hud_work_enabled:
            t_p_end = time.perf_counter()
            return PreparedFrame(
                frame_idx=idx,
                sample_time_seconds=sample_time_sec,
                curr_dt=c_dt,
                hud_work_enabled=False,
                producer_prepare_ms=(t_p_end - t_p_start) * 1000.0,
                t_prod_begin=t_p_start,
                t_prod_end=t_p_end,
                native_hud_mode=native_hud_mode,
                full_hud_upload=False,
                dirty_rects=[],
                dirty_rect_slices=[],
                hud_backing_array=None,
                rgba_bytes_reference=None,
                chart_static_uploads=[],
                chart_dynamic_tiles=[],
                gauge_active=False,
                gauge_data=None,
                above_regions=[],
                map_active=False,
                map_data=None,
                map_geometry=None,
                timing_samples_producer={},
                intermediate_bytes=0,
                persistent_copy_bytes=0,
                upload_bytes=0,
                rect_count=0,
                above_stats={},
            )
            
        chart_data = WORKER_CACHE.get("_precomputed_chart_data", {})
        telemetry_start = time.perf_counter()
        t_dt_start = time.perf_counter()
        t_dt_ms = (time.perf_counter() - t_dt_start) * 1000.0

        if (
            telemetry_mode == "PRECOMPUTED"
            and telemetry_cache is not None
            and idx < len(telemetry_cache.records)
        ):
            t_lookup_start = time.perf_counter()
            frame_kwargs = telemetry_cache.lookup(idx)
            t_lookup_ms = (time.perf_counter() - t_lookup_start) * 1000.0
            t_payload_ms = t_lookup_ms * 0.6
            t_shared_ms = t_lookup_ms * 0.4
        else:
            t_lookup_start = time.perf_counter()
            frame_kwargs = _live_frame_data(idx, c_dt, chart_data)
            t_lookup_ms = (time.perf_counter() - t_lookup_start) * 1000.0
            t_payload_ms = t_lookup_ms * 0.8
            t_shared_ms = t_lookup_ms * 0.2

        telemetry_elapsed_ms = (time.perf_counter() - telemetry_start) * 1000.0
        t_other_ms = max(0.0, telemetry_elapsed_ms - t_lookup_ms - t_dt_ms)
        
        t_samples_p["Telemetry/frame_data"] = telemetry_elapsed_ms
        t_samples_p["telemetry_target_dt"] = t_dt_ms
        t_samples_p["telemetry_cache_lookup"] = t_lookup_ms
        t_samples_p["telemetry_frame_payload"] = t_payload_ms
        t_samples_p["telemetry_shared_objects"] = t_shared_ms
        t_samples_p["telemetry_other"] = t_other_ms
        
        nonlocal gpu_chart_keys, gpu_chart_reason, gauge_gpu_active, gauge_gpu_reason
        if idx == 0 and gpu_charts_requested and not gpu_chart_keys:
            _probe_capture: dict[str, dict[str, Any]] = {}
            _probe_bboxes: dict[str, tuple[int, int, int, int]] = {}
            _probe_render_keys = set(semantic_layout.get("indicators", {})) - {"track_map"}
            _probe_render_keys.update(
                f"custom_text:{idx}" for idx, _ in enumerate(semantic_layout.get("custom_texts", []))
            )
            compose_overlay(
                canvas_w=video_width, canvas_h=video_height,
                layout=semantic_layout, font_path=font_path,
                _bboxes=_probe_bboxes,
                gpu_capture_keys=set(_CHART_GPU_SLOTS.keys()),
                gpu_capture=_probe_capture,
                split_chart_keys=(
                    set(_CHART_GPU_SLOTS.keys()) if gpu_charts_split else None
                ),
                render_keys=_probe_render_keys,
                reuse_canvas=False,
                **frame_kwargs,
            )
            _probe_map_dst = None
            if gpu_map_enabled:
                _p_img, _p_dst = render_map_working_image(
                    video_width, video_height, layout, "track_map",
                    gps_track, target_dt=c_dt,
                    current_position=frame_kwargs.get("current_position"),
                    map_heading=frame_kwargs.get("map_heading"),
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

        _bboxes = {}
        gpu_capture: dict[str, dict[str, Any]] = {}
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
            reuse_canvas="below",
            **frame_kwargs
        )
        compose_elapsed_ms = (time.perf_counter() - compose_start) * 1000.0
        t_samples_p["compose_overlay"] = compose_elapsed_ms

        # Above Map multi-region
        above_regions_out = []
        above_compose_ms = 0.0
        above_region_plan_ms = 0.0
        above_candidate_crop_ms = 0.0
        above_local_alpha_scan_ms = 0.0
        above_final_crop_ms = 0.0
        above_region_to_bytes_ms = 0.0
        above_candidate_pixels = 0
        above_scanned_pixels = 0
        above_uploaded_pixels = 0
        above_uploaded_bytes = 0
        
        if map_above_layout is not None:
            above_bboxes: dict[str, tuple[int, int, int, int]] = {}
            above_cache_enabled = os.getenv("AMD_ABOVE_TEXT_CACHE", "1") != "0"
            above_reuse = "above" if above_cache_enabled else False
            above_compose_start = time.perf_counter()
            above_full = compose_overlay(
                canvas_w=video_width,
                canvas_h=video_height,
                layout=map_above_layout,
                font_path=font_path,
                _bboxes=above_bboxes,
                gpu_capture_keys=set(),
                split_chart_keys=None,
                reuse_canvas=above_reuse,
                **frame_kwargs,
            )
            above_compose_ms = (time.perf_counter() - above_compose_start) * 1000.0
            
            plan_start = time.perf_counter()
            if os.getenv("AMD_ABOVE_MULTI_REGION", "1") != "0":
                candidate_clusters = _cluster_above_bboxes(
                    above_bboxes, video_width, video_height, pad=16, merge_dist=32, max_regions=16
                )
            else:
                cand = _rendered_bbox_union(
                    above_bboxes, video_width, video_height, pad=64
                )
                candidate_clusters = [cand] if cand is not None else []
            above_region_plan_ms = (time.perf_counter() - plan_start) * 1000.0

            for cx, cy, cw, ch in candidate_clusters:
                above_candidate_pixels += cw * ch
                t_cand_start = time.perf_counter()
                candidate_image = above_full.crop((cx, cy, cx + cw, cy + ch))
                above_candidate_crop_ms += (time.perf_counter() - t_cand_start) * 1000.0

                t_alpha_start = time.perf_counter()
                local_alpha_bbox = candidate_image.getchannel("A").getbbox()
                above_local_alpha_scan_ms += (time.perf_counter() - t_alpha_start) * 1000.0
                above_scanned_pixels += cw * ch

                if local_alpha_bbox is not None:
                    lx, ly, rx, by = local_alpha_bbox
                    reg_w = rx - lx
                    reg_h = by - ly
                    if reg_w > 0 and reg_h > 0:
                        t_final_start = time.perf_counter()
                        reg_img = candidate_image.crop(local_alpha_bbox)
                        above_final_crop_ms += (time.perf_counter() - t_final_start) * 1000.0
                        reg_x = cx + lx
                        reg_y = cy + ly
                        above_uploaded_pixels += reg_w * reg_h
                        t_b_start = time.perf_counter()
                        r_bytes = reg_img.tobytes("raw", "RGBA")
                        above_region_to_bytes_ms += (time.perf_counter() - t_b_start) * 1000.0
                        above_uploaded_bytes += len(r_bytes)
                        above_regions_out.append((reg_x, reg_y, reg_w, reg_h, r_bytes))

        above_bbox_crop_ms = (
            above_region_plan_ms + above_candidate_crop_ms
            + above_local_alpha_scan_ms + above_final_crop_ms
        )
        above_total_ms = (
            above_compose_ms + above_bbox_crop_ms + above_region_to_bytes_ms
        )
        t_samples_p["above_compose"] = above_compose_ms
        t_samples_p["above_bbox_crop"] = above_bbox_crop_ms
        t_samples_p["above_bbox_tracking"] = above_region_plan_ms
        t_samples_p["above_candidate_crop"] = above_candidate_crop_ms
        t_samples_p["above_local_alpha_scan"] = above_local_alpha_scan_ms
        t_samples_p["above_final_crop"] = above_final_crop_ms
        t_samples_p["above_region_to_bytes"] = above_region_to_bytes_ms
        t_samples_p["above_total"] = above_total_ms
        above_stats_p = {
            "region_count": len(above_regions_out),
            "candidate_pixels": above_candidate_pixels,
            "scanned_pixels": above_scanned_pixels,
            "uploaded_pixels": above_uploaded_pixels,
            "uploaded_bytes": above_uploaded_bytes,
        }

        # Charts static & dynamic tiles
        chart_static_uploads = []
        chart_dynamic_tiles = []
        chart_to_bytes_ms = 0.0
        chart_dyn_tobytes_ms = 0.0
        if gpu_capture:
            for chart_key in gpu_chart_keys:
                cap = gpu_capture.get(chart_key)
                if cap is None:
                    continue
                bx, by, bw, bh = cap["bbox"]
                slot = _CHART_GPU_SLOTS[chart_key]
                if gpu_charts_split and cap.get("split"):
                    static_img = cap["static"]
                    if chart_key not in chart_static_uploaded:
                        chart_static_uploaded.add(chart_key)
                        tb_start = time.perf_counter()
                        st_bytes = static_img.tobytes("raw", "RGBA")
                        chart_to_bytes_ms = max(chart_to_bytes_ms, (time.perf_counter() - tb_start) * 1000.0)
                        chart_static_uploads.append((slot, st_bytes, static_img.width, static_img.height, bx, by, chart_key))
                    ct = cap["cursor_tile"]
                    if ct is not None:
                        cl = cap["cursor_local"]
                        dyn_tb_start = time.perf_counter()
                        cbytes = ct.tobytes("raw", "RGBA")
                        chart_dyn_tobytes_ms = max(chart_dyn_tobytes_ms, (time.perf_counter() - dyn_tb_start) * 1000.0)
                        chart_dynamic_tiles.append((slot, 0, cbytes, ct.width, ct.height, cl[0], cl[1]))
                    vt = cap["value_tile"]
                    if vt is not None:
                        vl = cap["value_local"]
                        dyn_tb_start = time.perf_counter()
                        vbytes = vt.tobytes("raw", "RGBA")
                        chart_dyn_tobytes_ms = max(chart_dyn_tobytes_ms, (time.perf_counter() - dyn_tb_start) * 1000.0)
                        chart_dynamic_tiles.append((slot, 1, vbytes, vt.width, vt.height, vl[0], vl[1]))
                else:
                    chart_img = cap.get("image")
                    if chart_img is not None:
                        tb_start = time.perf_counter()
                        chart_bytes = chart_img.tobytes("raw", "RGBA")
                        chart_to_bytes_ms = max(chart_to_bytes_ms, (time.perf_counter() - tb_start) * 1000.0)
                        chart_static_uploads.append((slot, chart_bytes, chart_img.width, chart_img.height, bx, by, chart_key))
                        
        t_samples_p["chart_cpu_tobytes"] = chart_to_bytes_ms
        t_samples_p["chart_dynamic_tobytes"] = chart_dyn_tobytes_ms

        # Gauge
        gauge_data = None
        gauge_tobytes_ms = 0.0
        if gauge_gpu_active:
            gauge_cap = gpu_capture.get(_GAUGE_KEY)
            if gauge_cap is not None and "image" in gauge_cap:
                gauge_img = gauge_cap["image"]
                gx, gy, gw, gh = gauge_cap["bbox"]
                cx0, cy0 = max(0, gx), max(0, gy)
                cx1, cy1 = min(video_width, gx + gw), min(video_height, gy + gh)
                if cx1 > cx0 and cy1 > cy0:
                    gauge_img = gauge_img.crop((cx0 - gx, cy0 - gy, cx1 - gx, cy1 - gy))
                    gx, gy, gw, gh = cx0, cy0, cx1 - cx0, cy1 - cy0
                    tb_start = time.perf_counter()
                    gauge_bytes = gauge_img.tobytes("raw", "RGBA")
                    gauge_tobytes_ms = (time.perf_counter() - tb_start) * 1000.0
                    gauge_data = (gauge_bytes, gauge_img.width, gauge_img.height, gx, gy)
        t_samples_p["gauge_tobytes"] = gauge_tobytes_ms

        # Map
        map_data = None
        map_geometry = None
        last_map_img_out = None
        last_map_dst_out = None
        map_timing_ms = 0.0
        if gpu_map_enabled:
            map_start = time.perf_counter()
            map_img, map_dst = render_map_working_image(
                video_width, video_height, layout, "track_map",
                gps_track, target_dt=c_dt, current_position=frame_kwargs.get("current_position"),
                map_heading=frame_kwargs.get("map_heading"),
            )
            if map_img is not None and map_dst is not None:
                last_map_img_out = map_img
                last_map_dst_out = map_dst
                if not map_geometry_set_holder[0]:
                    map_geometry_set_holder[0] = True
                    dst_x, dst_y, out_w, out_h = map_dst
                    src_w, src_h = map_img.size
                    map_geometry = (dst_x, dst_y, src_w, src_h, out_w, out_h)
                map_bytes = map_img.tobytes("raw", "RGBA")
                map_data = (map_bytes, map_img.width, map_img.height, map_dst)
            map_timing_ms = (time.perf_counter() - map_start) * 1000.0
        t_samples_p["map_cpu_upload"] = map_timing_ms

        # HUD Below dirty rects & backing
        dirty_rect_slices = []
        hud_backing_array = None
        rgba_bytes_reference = None
        dirty_rects = []
        full_upload = hud_upload_mode == "FULL" or idx == 0
        intermediate_bytes = 0
        persistent_copy_bytes = 0
        upload_bytes = 0
        rect_count = 0
        
        if native_hud_mode == "CPU_REFERENCE":
            tb_start = time.perf_counter()
            rgba_bytes_reference = composed_img.tobytes("raw", "RGBA")
            t_samples_p["PIL tobytes"] = (time.perf_counter() - tb_start) * 1000.0
        else:
            buffer_prep_start = time.perf_counter()
            if full_upload:
                hud_backing_array = np.array(composed_img, dtype=np.uint8, copy=True)
                dirty_rects = []
                intermediate_bytes = hud_frame_bytes
                persistent_copy_bytes = hud_frame_bytes
                upload_bytes = hud_frame_bytes
                rect_count = 1
            else:
                bbox_start = time.perf_counter()
                dirty_rects = _dirty_rects_from_bboxes(
                    previous_bboxes_holder[0], _bboxes,
                    video_width, video_height, dirty_max_rects,
                )
                t_samples_p["HUD dirty bbox"] = (time.perf_counter() - bbox_start) * 1000.0
                extract_start = time.perf_counter()
                for x, y, rect_w, rect_h in dirty_rects:
                    region = composed_img.crop((x, y, x + rect_w, y + rect_h))
                    region_bytes = region.tobytes("raw", "RGBA")
                    dirty_rect_slices.append((x, y, rect_w, rect_h, region_bytes))
                    persistent_copy_bytes += rect_w * rect_h * 4
                    upload_bytes += rect_w * rect_h * 4
                t_samples_p["HUD dirty extract"] = (time.perf_counter() - extract_start) * 1000.0
                rect_count = len(dirty_rects)
            t_samples_p["PIL/buffer preparation"] = (time.perf_counter() - buffer_prep_start) * 1000.0
            previous_bboxes_holder[0] = dict(_bboxes)

        t_p_end = time.perf_counter()
        prep_ms = (t_p_end - t_p_start) * 1000.0
        
        return PreparedFrame(
            frame_idx=idx,
            sample_time_seconds=sample_time_sec,
            curr_dt=c_dt,
            hud_work_enabled=True,
            producer_prepare_ms=prep_ms,
            t_prod_begin=t_p_start,
            t_prod_end=t_p_end,
            native_hud_mode=native_hud_mode,
            full_hud_upload=full_upload,
            dirty_rects=dirty_rects,
            dirty_rect_slices=dirty_rect_slices,
            hud_backing_array=hud_backing_array,
            rgba_bytes_reference=rgba_bytes_reference,
            chart_static_uploads=chart_static_uploads,
            chart_dynamic_tiles=chart_dynamic_tiles,
            gauge_active=gauge_gpu_active,
            gauge_data=gauge_data,
            above_regions=above_regions_out,
            map_active=gpu_map_enabled,
            map_data=map_data,
            map_geometry=map_geometry,
            timing_samples_producer=t_samples_p,
            intermediate_bytes=intermediate_bytes,
            persistent_copy_bytes=persistent_copy_bytes,
            upload_bytes=upload_bytes,
            rect_count=rect_count,
            above_stats=above_stats_p,
            last_map_img=last_map_img_out,
            last_map_dst=last_map_dst_out,
        )

    def _consume_prepared_frame(prepared: PreparedFrame) -> bool:
        nonlocal decoded_frames_python, hud_frames, successful_hud_updates, successful_video_updates
        nonlocal map_uploaded_bytes_total, map_gpu_frames, gauge_gpu_frames, gauge_uploaded_bytes_total
        nonlocal chart_static_uploads, chart_static_bytes_total, chart_dynamic_uploads, chart_dynamic_bytes_total
        nonlocal chart_full_tobytes_total, chart_split_frames, chart_uploaded_bytes_total
        nonlocal above_map_frames, above_map_visible_frames, above_map_uploaded_bytes_total
        nonlocal t_first_frame_begin, t_first_frame_encoded, last_map_img, last_map_dst

        t_c_start = time.perf_counter()
        if t_first_frame_begin == 0.0:
            t_first_frame_begin = t_c_start
        frame_acct.begin_frame(prepared.frame_idx)
        
        # Merge producer timing samples
        for k_t, v_t in prepared.timing_samples_producer.items():
            timing_samples[k_t].append(v_t)
            
        timing_samples["producer_prepare"].append(prepared.producer_prepare_ms)
        pillow_intermediate_bytes.append(prepared.intermediate_bytes)
        python_persistent_copy_bytes.append(prepared.persistent_copy_bytes)
        requested_upload_bytes.append(prepared.upload_bytes)
        dirty_rect_counts.append(prepared.rect_count)

        if prepared.above_stats:
            above_region_counts_samples.append(prepared.above_stats.get("region_count", 0))
            above_candidate_pixels_samples.append(prepared.above_stats.get("candidate_pixels", 0))
            above_scanned_pixels_samples.append(prepared.above_stats.get("scanned_pixels", 0))
            above_uploaded_pixels_samples.append(prepared.above_stats.get("uploaded_pixels", 0))
            above_uploaded_bytes_samples.append(prepared.above_stats.get("uploaded_bytes", 0))

        # Decode step on consumer
        raw_nv12: bytes | None = None
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
                return False
            if read_status < 0:
                print("[AMD NATIVE D3D11VA] ERROR: native ReadSample failed.", flush=True)
                return False
            decoded_frames_python += 1
            if prepared.frame_idx in {0, 30, 300, 600, 900}:
                reference_pts = prepared.frame_idx / target_fps
                sample_timestamps[prepared.frame_idx] = {
                    "frame_index": prepared.frame_idx,
                    "mf_pts_100ns": int(sample_pts.value),
                    "mf_pts_seconds": sample_pts.value / 10_000_000.0,
                    "cpu_reference_seconds": reference_pts,
                    "delta_ms": ((sample_pts.value / 10_000_000.0) - reference_pts) * 1000.0,
                    "duration_100ns": int(sample_duration.value),
                    "dxgi_format": int(sample_format.value),
                    "subresource": int(sample_subresource.value),
                    "texture_pointer": hex(sample_texture.value),
                }
        else:
            assert proc_dec is not None and proc_dec.stdout is not None
            decode_wait_start = time.perf_counter()
            raw_nv12 = proc_dec.stdout.read(frame_size)
            decode_wait_ms = (time.perf_counter() - decode_wait_start) * 1000.0
            if len(raw_nv12) != frame_size:
                return False
            timing_samples["Decode/pipe wait"].append(decode_wait_ms)
            decoded_frames_python += 1

        t_up_stage_start = time.perf_counter()
        
        # Upload Charts
        for slot, st_bytes, sw, sh, bx, by, ch_key in prepared.chart_static_uploads:
            st_uploaded = c_uint64(0)
            st_created = c_int(0)
            ok = native_dll.telem_amd_update_chart_static(
                h_context, slot, st_bytes, sw, sh, sw * 4, bx, by, byref(st_uploaded), byref(st_created),
            )
            if ok:
                chart_static_uploads += 1
                chart_static_bytes_total += int(st_uploaded.value)
                
        for slot, reg_idx, dt_bytes, tw, th, lx, ly in prepared.chart_dynamic_tiles:
            c_up = c_uint64(0)
            ok = native_dll.telem_amd_update_chart_dynamic(
                h_context, slot, reg_idx, dt_bytes, tw, th, tw * 4, lx, ly, byref(c_up),
            )
            if ok:
                chart_dynamic_uploads += 1
                chart_dynamic_bytes_total += int(c_up.value)

        # Upload Gauge
        if prepared.gauge_data is not None:
            g_bytes, gw, gh, gx, gy = prepared.gauge_data
            g_uploaded = c_uint64(0)
            g_created = c_int(0)
            up_start = time.perf_counter()
            ok = native_dll.telem_amd_update_gauge(
                h_context, g_bytes, gw, gh, gw * 4, gx, gy, byref(g_uploaded), byref(g_created),
            )
            gauge_upload_ms = (time.perf_counter() - up_start) * 1000.0
            timing_samples["gauge_upload"].append(gauge_upload_ms)
            if ok:
                gauge_gpu_frames += 1
                gauge_uploaded_bytes_total += int(g_uploaded.value)

        # Upload Above Regions
        if map_above_layout is not None:
            reg_count = len(prepared.above_regions)
            native_dll.telem_amd_update_above_regions_count(h_context, reg_count)
            above_up_ms = 0.0
            for r_idx, (rx, ry, rw, rh, r_bytes) in enumerate(prepared.above_regions):
                r_ptr = (c_uint8 * len(r_bytes)).from_buffer_copy(r_bytes)
                t_r_start = time.perf_counter()
                r_ok = native_dll.telem_amd_update_above_region(
                    h_context, r_idx, r_ptr, rw, rh, rw * 4, rx, ry
                )
                above_up_ms += (time.perf_counter() - t_r_start) * 1000.0
                if r_ok:
                    above_map_uploaded_bytes_total += len(r_bytes)
            timing_samples["above_region_upload"].append(above_up_ms)
            above_map_frames += 1
            if reg_count > 0:
                above_map_visible_frames += 1

        # Upload Map
        if prepared.map_geometry is not None:
            dst_x, dst_y, src_w, src_h, out_w, out_h = prepared.map_geometry
            native_dll.telem_amd_set_map_geometry(
                h_context, dst_x, dst_y, src_w, src_h, out_w, out_h,
            )
        if prepared.map_data is not None:
            m_bytes, mw, mh, mdst = prepared.map_data
            last_map_img = prepared.last_map_img
            last_map_dst = prepared.last_map_dst
            m_uploaded = c_uint64(0)
            m_created = c_int(0)
            ok = native_dll.telem_amd_update_map(
                h_context, m_bytes, mw, mh, mw * 4, byref(m_uploaded), byref(m_created),
            )
            if ok:
                map_uploaded_bytes_total += int(m_uploaded.value)
                map_gpu_frames += 1

        # Upload HUD Below
        last_hud_call_ms = 0.0
        hud_update_ok = True
        if prepared.hud_work_enabled:
            if prepared.native_hud_mode == "CPU_REFERENCE":
                assert prepared.rgba_bytes_reference is not None
                update_hud_start = time.perf_counter()
                hud_update_ok = native_dll.telem_amd_update_hud(
                    h_context, prepared.rgba_bytes_reference, video_width, video_height, video_width * 4,
                )
                last_hud_call_ms = (time.perf_counter() - update_hud_start) * 1000.0
            else:
                assert hud_backing is not None and hud_backing_view is not None
                if prepared.full_hud_upload:
                    assert prepared.hud_backing_array is not None
                    np.copyto(hud_backing_view, prepared.hud_backing_array)
                    native_rect_ptr = None
                    native_rect_count = 0
                else:
                    for x, y, rect_w, rect_h, r_bytes in prepared.dirty_rect_slices:
                        r_arr = np.frombuffer(r_bytes, dtype=np.uint8).reshape(rect_h, rect_w, 4)
                        np.copyto(hud_backing_view[y:y + rect_h, x:x + rect_w], r_arr)
                    if prepared.dirty_rects:
                        native_rects = (_HUDDirtyRect * len(prepared.dirty_rects))(
                            *(_HUDDirtyRect(*rect) for rect in prepared.dirty_rects)
                        )
                        native_rect_ptr = native_rects
                        native_rect_count = len(prepared.dirty_rects)
                    else:
                        native_rect_ptr = None
                        native_rect_count = 0
                hud_pointer_observations.append(hud_backing_address)
                update_hud_start = time.perf_counter()
                hud_update_ok = native_dll.telem_amd_update_hud_regions(
                    h_context, hud_backing, video_width, video_height, video_width * 4,
                    native_rect_ptr, native_rect_count, 1 if prepared.full_hud_upload else 0,
                )
                last_hud_call_ms = (time.perf_counter() - update_hud_start) * 1000.0
            timing_samples["update_hud"].append(last_hud_call_ms)
            if not hud_update_ok:
                print(f"[AMD NATIVE D3D11] ERROR: telem_amd_update_hud failed on frame {prepared.frame_idx}", flush=True)
                return False
            successful_hud_updates += 1
            hud_frames += 1

        if not use_d3d11va:
            assert raw_nv12 is not None
            video_update_ok = native_dll.telem_amd_update_video_frame(
                h_context, raw_nv12, video_width, video_height, video_width,
            )
            if not video_update_ok:
                print(f"[AMD NATIVE D3D11] ERROR: telem_amd_update_video_frame failed on frame {prepared.frame_idx}", flush=True)
                return False
            successful_video_updates += 1

        t_up_stage_ms = (time.perf_counter() - t_up_stage_start) * 1000.0
        timing_samples["consumer_upload"].append(t_up_stage_ms)

        # Process Frame
        t_native_start = time.perf_counter()
        ret = native_dll.telem_amd_process_frame(h_context, prepared.frame_idx, 1 if hud_enabled else 0)
        t_native_ms = (time.perf_counter() - t_native_start) * 1000.0
        timing_samples["consumer_native_call"].append(t_native_ms)
        if not ret:
            print(f"[AMD NATIVE D3D11] ERROR: telem_amd_process_frame failed on frame {prepared.frame_idx}", flush=True)
            return False

        if t_first_frame_encoded == 0.0:
            t_first_frame_encoded = time.perf_counter()

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
            if name == "BlendRGBAToNV12" and not prepared.hud_work_enabled:
                continue
            timing_samples[name].append(float(value.value))
        if prepared.hud_work_enabled:
            native_copy_ms = float(native_timing_values[3].value)
            native_upload_ms = float(native_timing_values[4].value)
            timing_samples["Python->native bridge"].append(
                max(0.0, last_hud_call_ms - native_copy_ms - native_upload_ms)
            )

        t_c_end = time.perf_counter()
        pipeline_total_ms = (t_c_end - t_c_start) * 1000.0
        timing_samples["pipeline_total"].append(pipeline_total_ms)

        if prepared.frame_idx < 20:
            timeline_trace.append({
                "frame_idx": prepared.frame_idx,
                "prod_begin": prepared.t_prod_begin,
                "prod_end": prepared.t_prod_end,
                "cons_begin": t_c_start,
                "cons_end": t_c_end,
                "prod_ms": prepared.producer_prepare_ms,
                "cons_ms": pipeline_total_ms,
            })

        # Progress reporting
        expected_progress_frames = source_frames if use_d3d11va and source_frames else total_frames
        if (prepared.frame_idx + 1) % progress_interval == 0 or (prepared.frame_idx + 1) == expected_progress_frames:
            elapsed = time.time() - start_time
            fps = (prepared.frame_idx + 1) / elapsed if elapsed > 0 else 0
            eta = (expected_progress_frames - (prepared.frame_idx + 1)) / fps if fps > 0 else 0
            pct = int(((prepared.frame_idx + 1) / expected_progress_frames) * 100)
            m, s = divmod(int(elapsed), 60)
            em, es = divmod(int(eta), 60)
            stats_str = f"Render: {pct}% ({prepared.frame_idx+1}/{expected_progress_frames}) | {fps:.1f} FPS | {m:02d}:{s:02d} elapsed, ETA {em:02d}:{es:02d}"
            if progress_cb:
                progress_cb(pct, stats_str)
            if on_render_progress:
                t_video_pts = (prepared.frame_idx / target_fps) if target_fps > 0 else 0.0
                on_render_progress(
                    prepared.frame_idx + 1,
                    expected_progress_frames,
                    elapsed,
                    fps,
                    {"ts": t_video_pts, "frame_idx": prepared.frame_idx},
                )
            if time.time() - last_hud_report_holder[0] >= 1.0:
                last_hud_report_holder[0] = time.time()
                print(f"[AMD NATIVE D3D11] Frame {prepared.frame_idx+1}/{expected_progress_frames} ({fps:.1f} FPS)", flush=True)

        return True

    # Main Execution Switch: ASYNC (Producer-Consumer) vs SYNC (Diagnostic)
    try:
        if pipeline_mode == "ASYNC":
            q_depth = max(1, int(os.getenv("AMD_QUEUE_DEPTH", "2")))
            frame_queue: queue.Queue = queue.Queue(maxsize=q_depth)
            cancel_evt = cancel_event if cancel_event is not None else threading.Event()
            producer_error: list[Exception] = []

            def producer_worker():
                try:
                    for f_idx in range(total_frames):
                        if cancel_evt.is_set():
                            break
                        prep = _prepare_frame_cpu(f_idx)
                        t_put_start = time.perf_counter()
                        while not cancel_evt.is_set():
                            try:
                                frame_queue.put(prep, timeout=0.05)
                                t_put_ms = (time.perf_counter() - t_put_start) * 1000.0
                                timing_samples["producer_queue_wait"].append(t_put_ms)
                                break
                            except queue.Full:
                                continue
                except Exception as e:
                    producer_error.append(e)
                finally:
                    while not cancel_evt.is_set():
                        try:
                            frame_queue.put(_END_OF_STREAM, timeout=0.05)
                            break
                        except queue.Full:
                            continue

            prod_thread = threading.Thread(target=producer_worker, name="TeleM-CpuProducer", daemon=True)
            prod_thread.start()

            consumed_count = 0
            try:
                while consumed_count < total_frames:
                    t_get_start = time.perf_counter()
                    item = None
                    while not cancel_evt.is_set():
                        try:
                            item = frame_queue.get(timeout=0.05)
                            t_get_ms = (time.perf_counter() - t_get_start) * 1000.0
                            timing_samples["consumer_queue_wait"].append(t_get_ms)
                            break
                        except queue.Empty:
                            if producer_error:
                                raise producer_error[0]
                            continue
                    if cancel_evt.is_set():
                        print("[AMD NATIVE D3D11] Export cancelled by user.", flush=True)
                        _cleanup_native_resources()
                        return False
                    if item is _END_OF_STREAM:
                        break
                    assert isinstance(item, PreparedFrame)
                    assert item.frame_idx == consumed_count, f"Frame order violation: expected {consumed_count}, got {item.frame_idx}"
                    ok = _consume_prepared_frame(item)
                    if not ok:
                        # EOS reached normally from decoder
                        break
                    consumed_count += 1
            finally:
                cancel_evt.set()
                prod_thread.join(timeout=2.0)
                if prod_thread.is_alive():
                    print("[AMD NATIVE D3D11] WARNING: producer thread did not exit within 2.0s.", flush=True)
                if producer_error:
                    raise producer_error[0]
        else:
            # SYNC (Production Default / Diagnostic Reference)
            for f_idx in range(total_frames):
                if cancel_event is not None and cancel_event.is_set():
                    print("[AMD NATIVE D3D11] Export cancelled by user.", flush=True)
                    _cleanup_native_resources()
                    return False
                prep = _prepare_frame_cpu(f_idx)
                timing_samples["producer_queue_wait"].append(0.0)
                timing_samples["consumer_queue_wait"].append(0.0)
                ok = _consume_prepared_frame(prep)
                if not ok:
                    # EOS reached normally from decoder
                    break

        t_video_render_end = time.perf_counter()

        # Drain remaining buffered frames from AMF hardware encoder to .h265 bitstream
        flush_start = time.perf_counter()
        flush_ok = native_dll.telem_amd_flush(h_context)
        flush_ms = (time.perf_counter() - flush_start) * 1000.0
        if not flush_ok:
            print("[AMD NATIVE D3D11] ERROR: telem_amd_flush failed during drain!", flush=True)
            _cleanup_native_resources()
            return False

        c_decoded = c_uint64(0)
        c_vp = c_uint64(0)
        c_sub = c_uint64(0)
        c_rec = c_uint64(0)
        native_dll.telem_amd_get_stats(
            h_context, byref(c_decoded), byref(c_vp), byref(c_sub), byref(c_rec)
        )

        c_hud_updates = c_uint64(0)
        c_video_updates = c_uint64(0)
        c_input_full = c_uint64(0)
        c_retries = c_uint64(0)
        c_dropped = c_uint64(0)
        c_ignored = c_uint64(0)
        native_dll.telem_amd_get_extended_stats(
            h_context,
            byref(c_hud_updates),
            byref(c_video_updates),
            byref(c_input_full),
            byref(c_retries),
            byref(c_dropped),
            byref(c_ignored),
        )

        c_blend_calls = c_uint64(0)
        c_gpu_profiled_frames = c_uint64(0)
        native_dll.telem_amd_get_etap1_stats(
            h_context, byref(c_blend_calls), byref(c_gpu_profiled_frames)
        )

        c_gpu_hud_frames = c_uint64(0)
        c_hud_texture_creates = c_uint64(0)
        c_hud_texture_uploads = c_uint64(0)
        c_native_hud_mode = c_int(0)
        native_dll.telem_amd_get_etap2_stats(
            h_context,
            byref(c_gpu_hud_frames),
            byref(c_hud_texture_creates),
            byref(c_hud_texture_uploads),
            byref(c_native_hud_mode),
        )

        c_hud_uploaded_bytes = c_uint64(0)
        c_hud_uploaded_rects = c_uint64(0)
        native_dll.telem_amd_get_etap3_stats(
            h_context, byref(c_hud_uploaded_bytes), byref(c_hud_uploaded_rects)
        )

        c_mf_read_calls = c_uint64(0)
        c_mf_video_samples = c_uint64(0)
        c_mf_stream_ticks = c_uint64(0)
        c_mf_null_samples = c_uint64(0)
        c_mf_d3d11_surfaces = c_uint64(0)
        c_mf_format_changes = c_uint64(0)
        c_mf_eos_events = c_uint64(0)
        c_direct_surface_frames = c_uint64(0)
        c_decoder_gpu_copy_frames = c_uint64(0)
        c_native_decode_mode = c_int(0)
        c_hardware_decode_confirmed = c_int(0)
        c_decoder_format = c_uint(0)
        native_dll.telem_amd_get_etap4_stats(
            h_context,
            byref(c_mf_read_calls),
            byref(c_mf_video_samples),
            byref(c_mf_stream_ticks),
            byref(c_mf_null_samples),
            byref(c_mf_d3d11_surfaces),
            byref(c_mf_format_changes),
            byref(c_mf_eos_events),
            byref(c_direct_surface_frames),
            byref(c_decoder_gpu_copy_frames),
            byref(c_native_decode_mode),
            byref(c_hardware_decode_confirmed),
            byref(c_decoder_format),
        )
        # ETAP 8V-A: Explicitly close native context to flush GPU timestamp CSV and frame accounting trace
        _cleanup_native_resources()
    finally:
        _cleanup_native_resources()

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
        t_mux_begin = time.perf_counter()
        proc = subprocess.run(cmd_mux, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        t_mux_end = time.perf_counter()
        mux_elapsed_ms = (t_mux_end - t_mux_begin) * 1000.0
        timing_samples["Audio mux"].append(mux_elapsed_ms)
        if proc.returncode != 0:
            print(f"[AMD NATIVE D3D11] WARNING: FFmpeg remux failed, renaming raw bitstream.", flush=True)
            if os.path.exists(output_file_str): os.remove(output_file_str)
            os.rename(temp_h265, output_file_str)
        else:
            print(f"[AMD NATIVE D3D11] Remux complete. Final output: {output_file_str}", flush=True)
            if os.path.exists(temp_h265):
                for _ in range(10):
                    try:
                        os.remove(temp_h265)
                        break
                    except OSError:
                        time.sleep(0.05)

        final_probe = _probe_video_summary(ffmpeg_exe, output_file_str)
        muxed_frames = _stream_frame_count(final_probe, "video")
        audio_present = any(
            stream.get("codec_type") == "audio" for stream in final_probe.get("streams", [])
        )
    end_to_end_elapsed = time.perf_counter() - end_to_end_start
    t_export_end = time.perf_counter()

    precompute_build_ms = (t_precompute_end - t_precompute_begin) * 1000.0 if (telemetry_mode == "PRECOMPUTED" and t_precompute_begin > 0) else 0.0
    first_frame_encoded_ts = t_first_frame_encoded if t_first_frame_encoded > 0 else (t_first_frame_begin if t_first_frame_begin > 0 else t_export_start)
    delay_export_to_first_frame_ms = (first_frame_encoded_ts - t_export_start) * 1000.0
    first_frame_begin_ts = t_first_frame_begin if t_first_frame_begin > 0 else t_export_start
    video_render_wall_ms = (t_video_render_end - first_frame_begin_ts) * 1000.0
    mux_wall_ms = (t_mux_end - t_mux_begin) * 1000.0 if (t_mux_end > 0 and t_mux_begin > 0) else 0.0
    total_from_export_start_ms = (t_export_end - t_export_start) * 1000.0

    encoded_count = float(c_rec.value)
    render_fps = encoded_count / (video_render_wall_ms / 1000.0) if video_render_wall_ms > 0 else 0.0
    effective_fps = encoded_count / (total_from_export_start_ms / 1000.0) if total_from_export_start_ms > 0 else 0.0

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

    print("\n[AMD NATIVE ETAP 8P-A WALL TIMINGS]", flush=True)
    print(f"  EXPORT_CLICK / export_start:      0.000 ms (t=0.000 s)", flush=True)
    print(f"  PRECOMPUTE_BEGIN:                 {(t_precompute_begin - t_export_start)*1000.0:10.3f} ms", flush=True)
    print(f"  PRECOMPUTE_END:                   {(t_precompute_end - t_export_start)*1000.0:10.3f} ms", flush=True)
    print(f"  FIRST_FRAME_BEGIN:                {(t_first_frame_begin - t_export_start)*1000.0:10.3f} ms", flush=True)
    print(f"  FIRST_FRAME_ENCODED:              {(first_frame_encoded_ts - t_export_start)*1000.0:10.3f} ms", flush=True)
    print(f"  VIDEO_RENDER_END:                 {(t_video_render_end - t_export_start)*1000.0:10.3f} ms", flush=True)
    print(f"  MUX_BEGIN:                        {(t_mux_begin - t_export_start)*1000.0:10.3f} ms", flush=True)
    print(f"  MUX_END:                          {(t_mux_end - t_export_start)*1000.0:10.3f} ms", flush=True)
    print(f"  EXPORT_END:                       {total_from_export_start_ms:10.3f} ms", flush=True)

    print("\n[AMD NATIVE ETAP 8P-A SUMMARY]", flush=True)
    print(f"  precompute_build_ms:              {precompute_build_ms:.3f} ms ({precompute_build_ms/1000.0:.3f} s)", flush=True)
    print(f"  delay_export_to_first_frame_ms:   {delay_export_to_first_frame_ms:.3f} ms ({delay_export_to_first_frame_ms/1000.0:.3f} s)", flush=True)
    print(f"  video_render_wall_ms:             {video_render_wall_ms:.3f} ms ({video_render_wall_ms/1000.0:.3f} s)", flush=True)
    print(f"  mux_wall_ms:                      {mux_wall_ms:.3f} ms ({mux_wall_ms/1000.0:.3f} s)", flush=True)
    print(f"  TOTAL_FROM_EXPORT_START_ms:       {total_from_export_start_ms:.3f} ms ({total_from_export_start_ms/1000.0:.3f} s)", flush=True)
    print(f"  RENDER FPS:                       {render_fps:.3f} fps", flush=True)
    print(f"  USER EFFECTIVE FPS:               {effective_fps:.3f} fps", flush=True)

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
            "decoder_output_format": {104: "DXGI_FORMAT_P010", 87: "DXGI_FORMAT_B8G8R8A8_UNORM", 28: "DXGI_FORMAT_R8G8B8A8_UNORM"}.get(c_decoder_format.value, f"DXGI_FORMAT_{c_decoder_format.value}"),
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
            "map_gpu_path": map_gpu_path_name,
            "map_gpu_path_index": map_gpu_path_val,
            "map_gpu_direct_used": bool(native_dll.telem_amd_get_map_gpu_path_used(h_context)) if gpu_map_enabled else False,
            "map_gpu_frames": map_gpu_frames,
            "map_order": "CPU_BELOW_MAP -> GPU_MAP -> CPU_ABOVE_MAP" if gpu_map_enabled else "CPU_REFERENCE",
            "map_above_update_frames": above_map_frames,
            "map_above_visible_frames": above_map_visible_frames,
            "map_above_uploaded_bytes_total": above_map_uploaded_bytes_total,
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
        "etap8c": {
            "architecture": "rendered indicator bboxes -> cluster regions -> local candidate crops -> local alpha scans -> compact multi-region uploads",
            "full_frame_alpha_scan": False,
            "full_frame_alpha_pixels_scanned_per_frame": 0,
            "candidate_pixels": _value_summary(
                [float(v) for v in above_candidate_pixels_samples]
            ) if above_candidate_pixels_samples else None,
            "candidate_width": _value_summary(above_candidate_widths) if above_candidate_widths else None,
            "candidate_height": _value_summary(above_candidate_heights) if above_candidate_heights else None,
            "final_width": _value_summary(above_final_widths) if above_final_widths else None,
            "final_height": _value_summary(above_final_heights) if above_final_heights else None,
            "candidate_bbox_count": sum(1 for v in above_candidate_bbox_samples if v),
            "final_bbox_count": sum(1 for v in above_final_bbox_samples if v),
            "above_upload_bytes_total": above_map_uploaded_bytes_total,
            "above_upload_bytes_per_frame": (
                above_map_uploaded_bytes_total / max(1, above_map_frames)
                if above_map_frames else 0.0
            ),
        },
        "etap8n": {
            "multi_region_enabled": True,
            "full_frame_alpha_scan": False,
            "full_frame_alpha_pixels_scanned_per_frame": 0,
            "regions_per_frame": _value_summary(
                [float(v) for v in above_region_counts_samples]
            ) if above_region_counts_samples else None,
            "candidate_pixels_per_frame": _value_summary(
                [float(v) for v in above_candidate_pixels_samples]
            ) if above_candidate_pixels_samples else None,
            "scanned_pixels_per_frame": _value_summary(
                [float(v) for v in above_scanned_pixels_samples]
            ) if above_scanned_pixels_samples else None,
            "uploaded_pixels_per_frame": _value_summary(
                [float(v) for v in above_uploaded_pixels_samples]
            ) if above_uploaded_pixels_samples else None,
            "uploaded_bytes_per_frame": _value_summary(
                [float(v) for v in above_uploaded_bytes_samples]
            ) if above_uploaded_bytes_samples else None,
            "above_upload_bytes_total": above_map_uploaded_bytes_total,
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
        "etap5o": {"amf_mode": amf_mode, "amf_diag_enabled": amf_diag_enabled},
        "etap5p": {"enabled": False},
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
        "etap8o": {
            "telemetry_mode": telemetry_mode,
            "is_precomputed": telemetry_mode == "PRECOMPUTED",
            "precomputed_stats": (
                {
                    "frames": telemetry_cache.frames,
                    "build_ms": telemetry_cache.build_ms,
                    "memory_bytes": telemetry_cache.memory_bytes,
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
        "etap8p_a": {
            "precompute_build_ms": precompute_build_ms,
            "delay_export_to_first_frame_ms": delay_export_to_first_frame_ms,
            "video_render_wall_ms": video_render_wall_ms,
            "mux_wall_ms": mux_wall_ms,
            "total_from_export_start_ms": total_from_export_start_ms,
            "render_fps": render_fps,
            "effective_fps": effective_fps,
            "wall_milestones_ms": {
                "export_start": 0.0,
                "precompute_begin": (t_precompute_begin - t_export_start) * 1000.0 if t_precompute_begin > 0 else 0.0,
                "precompute_end": (t_precompute_end - t_export_start) * 1000.0 if t_precompute_end > 0 else 0.0,
                "first_frame_begin": (first_frame_begin_ts - t_export_start) * 1000.0 if first_frame_begin_ts > 0 else 0.0,
                "first_frame_encoded": (first_frame_encoded_ts - t_export_start) * 1000.0 if first_frame_encoded_ts > 0 else 0.0,
                "video_render_end": (t_video_render_end - t_export_start) * 1000.0 if t_video_render_end > 0 else 0.0,
                "mux_begin": (t_mux_begin - t_export_start) * 1000.0 if t_mux_begin > 0 else 0.0,
                "mux_end": (t_mux_end - t_export_start) * 1000.0 if t_mux_end > 0 else 0.0,
                "export_end": total_from_export_start_ms,
            },
        },
        "etap8q": {
            "above_text_cache_enabled": os.getenv("AMD_ABOVE_TEXT_CACHE", "1") != "0",
        },
                "etap8t_b": {
            "pipeline_mode": pipeline_mode,
            "queue_max_depth": 2,
            "timeline_trace": timeline_trace,
        },
        "etap8s": {
            "flush_mode": os.getenv("AMD_FLUSH_MODE", "BATCHED"),
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
