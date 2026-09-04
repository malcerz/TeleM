"""Production AMD Native D3D11 + AMF Exporter Pipeline for TeleM.

Integrates the native C++ Direct3D 11 GPU VideoProcessor, persistent Python/Pillow RGBA HUD buffer,
and direct AMD AMF hardware encoding inside telem_amd_native.dll.
"""

from __future__ import annotations

import os
import sys
import time
import math
import uuid
from fractions import Fraction
import json
import copy
import statistics
import subprocess
import tracemalloc
import ctypes
from ctypes import wintypes
import queue
import threading
from dataclasses import dataclass, field
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
from src.indicators.profiling import production_accounting_summary, record_production_accounting
from src.indicators.moving_map import (
    render_map_working_image,
    render_map_unrotated_working_image,
    build_static_map_marker_tile,
    _map_render_plan,
    _quantize_map_val,
)
from src.indicators.helpers import s, _parse_marker_color
from src.indicators.rotated_paste import (
    get_tight_bbox_collect_ms,
    reset_tight_bbox_collect,
)
# ETAP 2C: renderer-reported dynamic-support geometry for AUTO gauge regions.
from src.indicators.gauge import get_gauge_dynamic_info
from src.ffmpeg.worker_cache import init_worker, _resolve_cache_value, WORKER_CACHE


from ctypes import c_float
from src.ffmpeg.amd_config import make_benchmark_fingerprint, resolve_amd_config
from src.render_logging import render_debug_enabled, render_debug_print, render_print

# Keep one renderer verbosity switch for exporter diagnostics.  Warnings and
# errors remain visible; TELEM_RENDER_DEBUG=1 restores the detailed stream.
print = render_print
AMD_NATIVE_ABI_VERSION = 9

# ── ETAP 1A: Data contract for AFTER-MAP GPU_SPLIT Chart Capture ──────────────
@dataclass
class AfterMapChartTile:
    """ETAP 1A — Python capture tile and metadata contract for AFTER-MAP charts.

    Contains the static background layer and dynamic cursor/value tiles for a
    chart placed after the track_map. Prepared for the future native
    BlendAfterMapCharts pass (ETAP 1B).
    """
    chart_key: str
    slot: int
    placement: str # "AFTER_MAP"
    bbox: tuple[int, int, int, int] # (dst_x, dst_y, dst_w, dst_h) in canvas coordinates
    center: tuple[int, int]
    rotation: int

    # Static background layer
    static_bytes: Optional[bytes] # RGBA 8:8:8:8 bytes (populated on initial frame or cache invalidation)
    static_width: int
    static_height: int
    static_stride: int # static_width * 4

    # Dynamic cursor tile
    cursor_bytes: Optional[bytes] # RGBA bytes
    cursor_width: int
    cursor_height: int
    cursor_stride: int
    cursor_local: tuple[int, int] # (local_x, local_y) relative to chart top-left

    # Dynamic value text tile
    value_bytes: Optional[bytes] # RGBA bytes
    value_width: int
    value_height: int
    value_stride: int
    value_local: tuple[int, int] # (local_x, local_y) relative to chart top-left

    format: str = "DXGI_FORMAT_R8G8B8A8_UNORM"
    is_valid: bool = True


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
    map_heading: float
    
    # Diagnostics & Profiling
    timing_samples_producer: dict[str, float]
    intermediate_bytes: int
    persistent_copy_bytes: int
    upload_bytes: int
    rect_count: int
    above_stats: dict[str, Any]
    last_map_img: Optional[Any] = None
    last_map_dst: Optional[Any] = None
    map_crop_key: Optional[Any] = None

    # ETAP 1A: After-Map Chart GPU_SPLIT capture data (diagnostic in 1A)
    after_map_chart_captures: list[AfterMapChartTile] = field(default_factory=list)

    # ── ETAP 2B: dynamic-region transfer payloads (None => full/legacy path)
    gauge_region_data: Optional[list[tuple[bytes, int, int, int, int]]] = None # [(bytes, bx, by, bw, bh), ...]
    gauge_tile_bbox: Optional[tuple[int, int, int, int]] = None # (gx, gy, gw, gh)
    gauge_clear_only: bool = False # ETAP 2C AUTO: run clears, zero regions to upload

    # ── ETAP 2G: GPU lean indicator dynamic transform payload ──────────
    lean_active: bool = False
    lean_transform: Optional[tuple[float, float, float, float, float, int, int, int, int]] = None


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


def _resolve_gauge_layout_key(layout: Optional[dict]) -> str:
    """ETAP 2E: resolve the actual speed-gauge widget key for THIS layout.

    The GPU gauge pipeline historically hard-coded the v10 preset key
    (``fit_enhanced_speed_text``).  Real user projects may attach the gauge
    form to a different indicator key (``def_layout.json`` uses
    ``speed_text``), which made every probe / capture / dynamic-region lookup
    target a widget that does not exist -> ``bbox=None`` ->
    ``GPU gauge fallback -> CPU_REFERENCE (gauge not rendered)`` even though a
    gauge is visibly rendered on the CPU ABOVE layer.

    Resolution: first ENABLED indicator whose config declares
    ``form == "gauge"`` in layout order.  Falls back to the historical v10 key
    when nothing matches (legacy behaviour preserved).
    """
    indicators = (layout or {}).get("indicators", {})
    for key, cfg in indicators.items():
        if not isinstance(cfg, dict):
            continue
        if not cfg.get("enabled", True):
            continue
        if str(cfg.get("form", "")).strip().lower() == "gauge":
            return str(key)
    return _GAUGE_KEY

# ── ETAP 2C: AUTO dynamic-region derivation (renderer-semantics based) ────────
_GAUGE_AUTO_MAX_RECTS = 8      # hard cap — matches ETAP 2B consumer loop limit
_GAUGE_REGION_SAFETY_PX = 1    # exporter-side growth beyond renderer support


def _support_to_tile_rect(sup, off_x, off_y, gw, gh):
    """Widget-local float support bbox -> clamped tile-local (x0,y0,x1,y1).

    The renderer reports dynamic-element bounds in UNCLIPPED widget-image
    coordinates. Tile coordinates subtract the clip offset between the raw
    widget origin and the on-canvas tile origin, then clamp to the tile and
    grow by a small safety margin for rasterizer edge rounding.
    """
    if sup is None:
        return None
    try:
        x0, y0, x1, y1 = sup
        ix0 = int(math.floor(float(x0))) - int(off_x) - _GAUGE_REGION_SAFETY_PX
        iy0 = int(math.floor(float(y0))) - int(off_y) - _GAUGE_REGION_SAFETY_PX
        ix1 = int(math.ceil(float(x1))) - int(off_x) + _GAUGE_REGION_SAFETY_PX
        iy1 = int(math.ceil(float(y1))) - int(off_y) + _GAUGE_REGION_SAFETY_PX
    except (TypeError, ValueError):
        return None
    ix0 = max(0, min(ix0, gw))
    ix1 = max(0, min(ix1, gw))
    iy0 = max(0, min(iy0, gh))
    iy1 = max(0, min(iy1, gh))
    if ix1 <= ix0 or iy1 <= iy0:
        return None
    return (ix0, iy0, ix1, iy1)


def _union_tile_rects(a, b):
    """Bounding box of two (x0,y0,x1,y1) rects (None-aware)."""
    if a is None:
        return b
    if b is None:
        return a
    return (min(a[0], b[0]), min(a[1], b[1]),
            max(a[2], b[2]), max(a[3], b[3]))


def _rects_intersect(a, b):
    return not (a[2] <= b[0] or b[2] <= a[0]
                or a[3] <= b[1] or b[3] <= a[1])


def _merge_tile_rects(rects, max_rects=_GAUGE_AUTO_MAX_RECTS):
    """Reduce rect list to <= max_rects while keeping every original pixel.

    Overlapping pairs are merged first (minimal area growth); if the list is
    still too long, the smallest rects are collapsed into bounding boxes.
    Every returned rect is a union of input rects => superset guarantee.
    """
    rs = [tuple(int(v) for v in r) for r in rects if r is not None]
    merged = True
    while merged and len(rs) > max_rects:
        merged = False
        for i in range(len(rs)):
            for j in range(i + 1, len(rs)):
                if _rects_intersect(rs[i], rs[j]):
                    rs[i] = _union_tile_rects(rs[i], rs[j])
                    del rs[j]
                    merged = True
                    break
            if merged:
                break
    while len(rs) > max_rects:
        rs.sort(key=lambda r: (r[2] - r[0]) * (r[3] - r[1]))
        rs[0] = _union_tile_rects(rs[0], rs[1])
        del rs[1]
    return rs


def _gauge_gpu_layout_safe(
    gauge_bbox: Optional[tuple[int, int, int, int]],
    other_bboxes: dict[str, tuple[int, int, int, int]],
    chart_capture: dict[str, dict[str, Any]],
    map_dst: Optional[tuple[int, int, int, int]],
    gauge_key: str = _GAUGE_KEY,
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
        if key == gauge_key:
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


def _gauge_after_map_layout_safe(
    gauge_bbox: Optional[tuple[int, int, int, int]],
    after_map_bboxes: dict[str, tuple[int, int, int, int]],
) -> tuple[bool, str]:
    """ETAP 2A z-order guard for the AFTER-MAP GPU gauge composite.

    The GPU gauge blend (BlendGauge) now runs AFTER the map and BlendAboveMap,
    immediately before BlendAfterMapCharts.  In this position the gauge may
    legally overlap the map (it is drawn on top of it).

    The only constraint is that the gauge bbox must be disjoint from the
    other AFTER-MAP chart bboxes (HR / Cadence) to preserve their relative
    pixel z-order.  In v10 the gauge (center ~50%, 53%) and the charts
    (bottom 82%) are spatially separated, so this check always passes.

    Unsafe layouts (gauge overlapping an after-map chart) fall back to CPU.
    """
    if gauge_bbox is None:
        return False, "gauge not rendered"
    gx, gy, gw, gh = tuple(int(v) for v in gauge_bbox)
    for key, bbox in after_map_bboxes.items():
        bx, by, bw, bh = tuple(int(v) for v in bbox)
        if gx < bx + bw and bx < gx + gw and gy < by + bh and by < gy + gh:
            return False, f"gauge overlaps after-map widget {key} bbox=({bx},{by},{bw},{bh})"
    return True, "gauge disjoint from after-map widgets -> GPU-AFTER-MAP safe"


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
    # AMD_RENDER_PATH_AUDIT_2 (temporary): per-chart GPU_SPLIT decision trace.
    chart_trace = os.environ.get("AMD_CHART_TRACE", "0") == "1"
    for key, cap in chart_capture.items():
        if "bbox" not in cap:
            reasons.append(f"{key}: no bbox (not rendered)")
            if chart_trace:
                print(f"CHART_TRACE {key} requested=GPU_SPLIT final=CPU_REFERENCE reason='no bbox (not rendered)'", flush=True)
            continue
        if cap.get("rotation", 0) % 360 != 0:
            # The GPU blend cannot reproduce Pillow's rotation of the widget,
            # so a rotated chart must stay on the CPU path.
            reasons.append(f"{key}: non-zero rotation -> CPU_REFERENCE")
            if chart_trace:
                print(f"CHART_TRACE {key} requested=GPU_SPLIT final=CPU_REFERENCE reason='non-zero rotation {cap.get('rotation')}'", flush=True)
            continue
        cbox = tuple(int(v) for v in cap["bbox"])
        cx, cy, cw, ch = cbox
        overlap = False
        for bx, by, bw, bh in other_boxes:
            if cx < bx + bw and bx < cx + cw and cy < by + bh and by < cy + ch:
                overlap = True
                reasons.append(f"{key} overlaps widget bbox=({bx},{by},{bw},{bh})")
                if chart_trace:
                    print(f"CHART_TRACE {key} requested=GPU_SPLIT final=CPU_REFERENCE reason='overlaps widget bbox=({bx},{by},{bw},{bh})' map_dst={map_dst}", flush=True)
                break
        if not overlap:
            safe.add(key)
            if chart_trace:
                print(f"CHART_TRACE {key} requested=GPU_SPLIT final=GPU reason='z-order disjoint (bbox={cbox})'", flush=True)
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
        if key == "time_display":
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
        if key != "time_display"
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


def _cluster_above_bboxes_members(
    bboxes: dict[str, tuple[int, int, int, int]],
    canvas_w: int,
    canvas_h: int,
    pad: int = 16,
    merge_dist: int = 32,
    max_regions: int = 16,
) -> list[tuple[tuple[int, int, int, int], list[str]]]:
    """Like ``_cluster_above_bboxes`` but also reports each cluster's member keys.

    Uses exactly the same pad / merge_dist / max_regions rules, so the
    candidate rects are identical to ``_cluster_above_bboxes``; only the
    member-key tracking is added (verified by test).  Used by the ETAP 10R
    EXACT path to union the per-widget tight bboxes of exactly the widgets
    that belong to each cluster.
    """
    valid: list[tuple[str, tuple[int, int, int, int]]] = []
    for key, box in bboxes.items():
        if not box or int(box[2]) <= 0 or int(box[3]) <= 0:
            continue
        clipped = _clip_rect(box, canvas_w, canvas_h, pad=pad)
        if clipped is not None:
            valid.append((key, clipped))

    if not valid:
        return []

    m_rects: list[tuple[int, int, int, int]] = [r for _, r in valid]
    m_members: list[list[str]] = [[k] for k, _ in valid]

    changed = True
    while changed:
        changed = False
        for i in range(len(m_rects)):
            for j in range(i + 1, len(m_rects)):
                r1, r2 = m_rects[i], m_rects[j]
                dx = max(0, max(r1[0], r2[0]) - min(r1[0] + r1[2], r2[0] + r2[2]))
                dy = max(0, max(r1[1], r2[1]) - min(r1[1] + r1[3], r2[1] + r2[3]))
                if dx <= merge_dist and dy <= merge_dist:
                    union_box = _rect_union(r1, r2)
                    new_members = m_members[i] + m_members[j]
                    m_rects.pop(j)
                    m_rects.pop(i)
                    m_members.pop(j)
                    m_members.pop(i)
                    m_rects.append(union_box)
                    m_members.append(new_members)
                    changed = True
                    break
            if changed:
                break

    while len(m_rects) > max_regions:
        best_pair: tuple[int, int] | None = None
        min_dist_sq = float("inf")
        for i in range(len(m_rects)):
            for j in range(i + 1, len(m_rects)):
                r1, r2 = m_rects[i], m_rects[j]
                c1 = (r1[0] + r1[2] / 2.0, r1[1] + r1[3] / 2.0)
                c2 = (r2[0] + r2[2] / 2.0, r2[1] + r2[3] / 2.0)
                dist_sq = (c1[0] - c2[0]) ** 2 + (c1[1] - c2[1]) ** 2
                if dist_sq < min_dist_sq:
                    min_dist_sq = dist_sq
                    best_pair = (i, j)
        if best_pair is None:
            break
        i, j = best_pair
        union_box = _rect_union(m_rects[i], m_rects[j])
        new_members = m_members[i] + m_members[j]
        m_rects.pop(j)
        m_rects.pop(i)
        m_members.pop(j)
        m_members.pop(i)
        m_rects.append(union_box)
        m_members.append(new_members)

    return [(rect, members) for rect, members in zip(m_rects, m_members)]


def _cluster_area_cost_members(
    bboxes: dict[str, tuple[int, int, int, int]],
    canvas_w: int,
    canvas_h: int,
    pad: int = 0,
    max_regions: int = 8,
) -> list[tuple[tuple[int, int, int, int], list[str]]]:
    """ETAP 5J: Area-Cost Aware Bounded Cluster Planner.
    Merges candidate rects that minimize added empty area: Area(Union(A,B)) - Area(A) - Area(B).
    """
    if not bboxes:
        return []
    m_rects: list[tuple[int, int, int, int]] = []
    m_members: list[list[str]] = []
    for k, box in bboxes.items():
        clipped = _clip_rect(box, canvas_w, canvas_h, pad=pad)
        if clipped is not None and clipped[2] > 0 and clipped[3] > 0:
            m_rects.append(clipped)
            m_members.append([k])

    while len(m_rects) > max_regions:
        best_pair = None
        min_added_area = float("inf")
        for i in range(len(m_rects)):
            for j in range(i + 1, len(m_rects)):
                r1, r2 = m_rects[i], m_rects[j]
                u_box = _rect_union(r1, r2)
                u_area = u_box[2] * u_box[3]
                added_area = u_area - (r1[2] * r1[3]) - (r2[2] * r2[3])
                if added_area < min_added_area:
                    min_added_area = added_area
                    best_pair = (i, j)
        if best_pair is None:
            break
        i, j = best_pair
        union_box = _rect_union(m_rects[i], m_rects[j])
        new_members = m_members[i] + m_members[j]
        m_rects.pop(j)
        m_rects.pop(i)
        m_members.pop(j)
        m_members.pop(i)
        m_rects.append(union_box)
        m_members.append(new_members)

    return [(rect, members) for rect, members in zip(m_rects, m_members)]


def _extract_above_regions(
    above_full: "Image.Image",
    candidate_clusters: list[tuple[int, int, int, int]],
    mode: str,
) -> tuple[list[tuple[int, int, int, int, bytes]], dict[str, Any]]:
    """ETAP 10Q: extract ABOVE dirty regions from the composed canvas.

    ``mode == "SCAN"`` (legacy fallback, byte-identical to the pre-10Q code):

        candidate crop -> local alpha scan (getchannel A + getbbox)
        -> tight final crop -> tobytes

    ``mode == "CANDIDATE"`` (ETAP 10Q):

        candidate crop -> tobytes

    CANDIDATE skips the local alpha scan and the tight final crop and uploads
    the whole candidate region.  NOTE (ETAP 10Q verdict): CANDIDATE is NOT
    production-safe — the larger uploaded rect becomes the GPU
    ``ClearPreviousAboveMap`` erase region, which wipes map pixels under the
    transparent padding that the map redraw (bounded by ``map_dst``) does not
    restore, so the final raster differs from SCAN.  The CPU extraction here
    is content-correct (identical overlay, padding alpha == 0); the failure is
    purely the GPU erase-region interaction.  SCAN remains the production
    default.

    Returns ``(regions, stats)``; each region is
    ``(reg_x, reg_y, reg_w, reg_h, r_bytes)`` and ``stats`` mirrors the
    per-frame ``above_stats_p`` (candidate/scanned/uploaded pixels + bytes)
    plus the internal step timings in ms.
    """
    regions_out: list[tuple[int, int, int, int, bytes]] = []
    candidate_crop_ms = 0.0
    alpha_scan_ms = 0.0
    final_crop_ms = 0.0
    tobytes_ms = 0.0
    candidate_pixels = 0
    scanned_pixels = 0
    uploaded_pixels = 0
    uploaded_bytes = 0

    for cx, cy, cw, ch in candidate_clusters:
        candidate_pixels += cw * ch
        t_cand_start = time.perf_counter()
        candidate_image = above_full.crop((cx, cy, cx + cw, cy + ch))
        candidate_crop_ms += (time.perf_counter() - t_cand_start) * 1000.0

        if mode == "CANDIDATE":
            # ETAP 10Q: no alpha scan, no tight crop.  Upload the candidate
            # region as-is; transparent padding is a no-op in the GPU blend.
            reg_x, reg_y, reg_w, reg_h = cx, cy, cw, ch
            uploaded_pixels += reg_w * reg_h
            t_b_start = time.perf_counter()
            r_bytes = candidate_image.tobytes("raw", "RGBA")
            tobytes_ms += (time.perf_counter() - t_b_start) * 1000.0
            uploaded_bytes += len(r_bytes)
            regions_out.append((reg_x, reg_y, reg_w, reg_h, r_bytes))
            continue

        # SCAN (legacy fallback): local alpha scan + tight final crop.
        t_alpha_start = time.perf_counter()
        local_alpha_bbox = candidate_image.getchannel("A").getbbox()
        alpha_scan_ms += (time.perf_counter() - t_alpha_start) * 1000.0
        scanned_pixels += cw * ch
        if local_alpha_bbox is None:
            continue
        lx, ly, rx, by = local_alpha_bbox
        reg_w = rx - lx
        reg_h = by - ly
        if reg_w <= 0 or reg_h <= 0:
            continue
        t_final_start = time.perf_counter()
        reg_img = candidate_image.crop(local_alpha_bbox)
        final_crop_ms += (time.perf_counter() - t_final_start) * 1000.0
        reg_x = cx + lx
        reg_y = cy + ly
        uploaded_pixels += reg_w * reg_h
        t_b_start = time.perf_counter()
        r_bytes = reg_img.tobytes("raw", "RGBA")
        tobytes_ms += (time.perf_counter() - t_b_start) * 1000.0
        uploaded_bytes += len(r_bytes)
        regions_out.append((reg_x, reg_y, reg_w, reg_h, r_bytes))

    stats: dict[str, Any] = {
        "region_count": len(regions_out),
        "candidate_pixels": candidate_pixels,
        "scanned_pixels": scanned_pixels,
        "uploaded_pixels": uploaded_pixels,
        "uploaded_bytes": uploaded_bytes,
        "candidate_crop_ms": candidate_crop_ms,
        "alpha_scan_ms": alpha_scan_ms,
        "final_crop_ms": final_crop_ms,
        "tobytes_ms": tobytes_ms,
    }
    return regions_out, stats


class _ImagingMemoryInstance(ctypes.Structure):
    _fields_ = [
        ("mode", ctypes.c_char * 5),
        ("type", ctypes.c_int32),
        ("depth", ctypes.c_int32),
        ("bands", ctypes.c_int32),
        ("xsize", ctypes.c_int32),
        ("ysize", ctypes.c_int32),
        ("linesize", ctypes.c_int32),
        ("pixelsize", ctypes.c_int32),
        ("image", ctypes.POINTER(ctypes.c_void_p)),
    ]


class HUDDirtyRect(ctypes.Structure):
    _fields_ = [
        ("x", ctypes.c_uint),
        ("y", ctypes.c_uint),
        ("width", ctypes.c_uint),
        ("height", ctypes.c_uint),
    ]


def _extract_exact_above_regions(
    above_full: "Image.Image",
    clusters_with_members: list[tuple[tuple[int, int, int, int], list[str]]],
    tight_bboxes: dict[str, dict[str, Any]],
    canvas_w: int,
    canvas_h: int,
    batched_rects_buf: Optional[Any] = None,
) -> tuple[Any, dict[str, Any]]:
    """ETAP 10R EXACT + ETAP 4F DIRECT ZERO-COPY + ETAP 5K BATCHED: extract ABOVE dirty regions.

    For each candidate cluster ``(rect, members)`` the exact upload region is
    the union of the members' alpha-tight bboxes (no extra padding), clipped to
    the canvas.

    ETAP 5K: when ``batched_rects_buf`` is provided and all regions are valid,
    populates the persistent ctypes array of HUDDirtyRect descriptors and returns
    a single BATCHED descriptor tuple for 1 native call in C++.
    """
    t_extract_start = time.perf_counter()
    regions_out: list[Any] = []
    exact_rects: list[tuple[int, int, int, int]] = []
    exact_union_ms = 0.0
    exact_crop_ms = 0.0
    fallback_scan_ms = 0.0
    fallback_final_crop_ms = 0.0
    tobytes_ms = 0.0
    candidate_pixels = 0
    scanned_pixels = 0
    uploaded_pixels = 0
    uploaded_bytes = 0
    exact_clusters = 0
    fallback_clusters = 0
    non_contig_regions = 0
    fallback_reasons: dict[str, int] = {}

    for (cx, cy, cw, ch), members in clusters_with_members:
        candidate_pixels += cw * ch

        t_union_start = time.perf_counter()
        rects: list[tuple[int, int, int, int]] = []
        unsafe = False
        reason: str | None = None
        for m in members:
            entry = tight_bboxes.get(m)
            if entry is None:
                unsafe = True
                reason = "missing_tight_bbox"
                break
            if entry.get("clipped"):
                unsafe = True
                reason = "clipped_widget"
                break
            r = entry.get("rect")
            if r is not None:
                rects.append(tuple(int(v) for v in r))
        if not unsafe and rects:
            left = min(r[0] for r in rects)
            top = min(r[1] for r in rects)
            right = max(r[0] + r[2] for r in rects)
            bottom = max(r[1] + r[3] for r in rects)
            exact_rect = _clip_rect(
                (left, top, right - left, bottom - top), canvas_w, canvas_h, pad=0
            )
            if exact_rect is None:
                unsafe = True
                reason = "invalid_exact_rect"
        else:
            exact_rect = None
        exact_union_ms += (time.perf_counter() - t_union_start) * 1000.0

        if unsafe:
            fallback_clusters += 1
            fallback_reasons[reason or "unknown"] = (
                fallback_reasons.get(reason or "unknown", 0) + 1
            )
            t_scan_start = time.perf_counter()
            candidate_image = above_full.crop((cx, cy, cx + cw, cy + ch))
            local_alpha_bbox = candidate_image.getchannel("A").getbbox()
            fallback_scan_ms += (time.perf_counter() - t_scan_start) * 1000.0
            scanned_pixels += cw * ch
            if local_alpha_bbox is not None:
                lx, ly, rx, by = local_alpha_bbox
                reg_w, reg_h = rx - lx, by - ly
                if reg_w > 0 and reg_h > 0:
                    t_final_start = time.perf_counter()
                    reg_img = candidate_image.crop(local_alpha_bbox)
                    fallback_final_crop_ms += (
                        time.perf_counter() - t_final_start
                    ) * 1000.0
                    reg_x, reg_y = cx + lx, cy + ly
                    uploaded_pixels += reg_w * reg_h
                    t_b_start = time.perf_counter()
                    r_bytes = reg_img.tobytes("raw", "RGBA")
                    tobytes_ms += (time.perf_counter() - t_b_start) * 1000.0
                    uploaded_bytes += len(r_bytes)
                    regions_out.append((reg_x, reg_y, reg_w, reg_h, r_bytes))
            continue

        exact_clusters += 1
        if exact_rect is None:
            # All members fully transparent -> no content -> no region
            continue
        ex, ey, ew, eh = exact_rect
        uploaded_pixels += ew * eh
        uploaded_bytes += ew * eh * 4
        exact_rects.append(exact_rect)

        t_crop_start = time.perf_counter()
        reg_img = above_full.crop((ex, ey, ex + ew, ey + eh))
        exact_crop_ms += (time.perf_counter() - t_crop_start) * 1000.0
        t_b_start = time.perf_counter()
        r_bytes = reg_img.tobytes("raw", "RGBA")
        tobytes_ms += (time.perf_counter() - t_b_start) * 1000.0
        regions_out.append((ex, ey, ew, eh, r_bytes))

    final_output = regions_out

    stats: dict[str, Any] = {
        "region_count": len(regions_out),
        "candidate_pixels": candidate_pixels,
        "scanned_pixels": scanned_pixels,
        "uploaded_pixels": uploaded_pixels,
        "uploaded_bytes": uploaded_bytes,
        "candidate_crop_ms": 0.0,
        "alpha_scan_ms": fallback_scan_ms,
        "final_crop_ms": fallback_final_crop_ms,
        "tobytes_ms": tobytes_ms,
        "tight_bbox_collect_ms": get_tight_bbox_collect_ms(),
        "exact_union_ms": exact_union_ms,
        "exact_crop_ms": exact_crop_ms,
        "exact_clusters": exact_clusters,
        "scan_fallback_clusters": fallback_clusters,
        "fallback_reason": fallback_reasons,
        "extract_ms": (time.perf_counter() - t_extract_start) * 1000.0,
    }
    return final_output, stats


def _extract_fine_dynamic_above_regions(
    above_full: "Image.Image",
    above_bboxes: dict[str, tuple[int, int, int, int]],
    above_tight_bboxes: dict[str, Any],
    prev_fine_dirty: dict[str, tuple[int, int, int, int]],
    canvas_w: int,
    canvas_h: int,
    pad: int = 4,
    merge_dist: int = 16,
    max_regions: int = 8,
) -> tuple[list[tuple[int, int, int, int, bytes]], dict[str, Any], dict[str, tuple[int, int, int, int]]]:
    """ETAP 3H: Extract fine-grained dynamic dirty regions unioned with previous frame's dynamic bbox."""
    t_start = time.perf_counter()
    new_prev_dirty: dict[str, tuple[int, int, int, int]] = {}
    fine_candidate_rects: list[tuple[int, int, int, int]] = []

    for k, box in above_bboxes.items():
        tight = above_tight_bboxes.get(k)
        if isinstance(tight, dict) and "bbox" in tight:
            curr_dyn = tight["bbox"]
        elif isinstance(tight, (tuple, list)):
            curr_dyn = tuple(tight)
        else:
            curr_dyn = box

        prev_dyn = prev_fine_dirty.get(k, curr_dyn)
        union_box = _rect_union(prev_dyn, curr_dyn)
        clipped = _clip_rect(union_box, canvas_w, canvas_h, pad=pad)
        if clipped is not None and clipped[2] > 0 and clipped[3] > 0:
            fine_candidate_rects.append(clipped)
        new_prev_dirty[k] = curr_dyn

    # Merge overlapping or close candidate rectangles using bounded planner
    merged = _cluster_above_bboxes(
        {f"dyn_{i}": r for i, r in enumerate(fine_candidate_rects)},
        canvas_w, canvas_h, pad=0, merge_dist=merge_dist, max_regions=max_regions,
    )

    plan_ms = (time.perf_counter() - t_start) * 1000.0

    regions_out: list[Any] = []
    crop_ms = 0.0
    tobytes_ms = 0.0
    uploaded_pixels = 0
    uploaded_bytes = 0

    for cx, cy, cw, ch in merged:
        uploaded_pixels += cw * ch
        uploaded_bytes += cw * ch * 4
        t_c = time.perf_counter()
        patch = above_full.crop((cx, cy, cx + cw, cy + ch))
        crop_ms += (time.perf_counter() - t_c) * 1000.0

        t_b = time.perf_counter()
        r_bytes = patch.tobytes("raw", "RGBA")
        tobytes_ms += (time.perf_counter() - t_b) * 1000.0
        regions_out.append((cx, cy, cw, ch, r_bytes))

    stats: dict[str, Any] = {
        "region_count": len(regions_out),
        "candidate_pixels": uploaded_pixels,
        "scanned_pixels": 0,
        "uploaded_pixels": uploaded_pixels,
        "uploaded_bytes": uploaded_bytes,
        "candidate_crop_ms": 0.0,
        "alpha_scan_ms": 0.0,
        "final_crop_ms": 0.0,
        "exact_crop_ms": crop_ms,
        "tobytes_ms": tobytes_ms,
        "tight_bbox_collect_ms": get_tight_bbox_collect_ms(),
        "exact_union_ms": plan_ms,
        "exact_clusters": len(merged),
        "scan_fallback_clusters": 0,
        "fallback_reason": {},
    }
    return regions_out, stats, new_prev_dirty


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


class _QueueTruth:
    """ETAP 5Q: in-memory producer/consumer queue truth, no per-frame I/O."""

    def __init__(self, enabled: bool) -> None:
        self.enabled = enabled
        self.maxsize = 0
        self.events: dict[int, dict[str, float | int]] = {}
        self.put_block_ms: list[float] = []
        self.get_block_ms: list[float] = []
        self.put_full_frames = 0
        self.get_empty_frames = 0
        self.put_sizes_before: dict[int, int] = {}
        self.put_sizes_after: dict[int, int] = {}
        self.get_sizes_after: dict[int, int] = {}

    def configure(self, maxsize: int) -> None:
        self.maxsize = maxsize

    def put_begin(self, frame: int, size: int) -> float:
        now = time.perf_counter()
        if self.enabled:
            self.put_sizes_before[frame] = size
            self.events.setdefault(frame, {})["producer_put_begin"] = now
            self.events[frame]["queue_size_before_put"] = size
            if size >= self.maxsize:
                self.put_full_frames += 1
                self.events[frame]["producer_queue_full"] = 1
        return now

    def put_end(self, frame: int, begin: float, size: int) -> None:
        if self.enabled:
            elapsed = (time.perf_counter() - begin) * 1000.0
            self.put_block_ms.append(elapsed)
            self.put_sizes_after[frame] = size
            event = self.events.setdefault(frame, {})
            event["producer_enqueue_complete"] = time.perf_counter()
            event["producer_blocked_ms"] = elapsed
            event["queue_size_after_put"] = size

    def get_begin(self, frame: int, size: int) -> float:
        now = time.perf_counter()
        if self.enabled:
            event = self.events.setdefault(frame, {})
            event["consumer_get_begin"] = now
            event["queue_size_before_get"] = size
            if size == 0:
                self.get_empty_frames += 1
                event["consumer_queue_empty"] = 1
        return now

    def get_end(self, frame: int, begin: float, size_after: int) -> None:
        if self.enabled:
            elapsed = (time.perf_counter() - begin) * 1000.0
            self.get_block_ms.append(elapsed)
            event = self.events.setdefault(frame, {})
            event["consumer_dequeue"] = time.perf_counter()
            event["consumer_blocked_ms"] = elapsed
            event["queue_size_after_get"] = size_after
            self.get_sizes_after[frame] = size_after

    def mark(self, frame: int, name: str) -> None:
        if self.enabled:
            self.events.setdefault(frame, {})[name] = time.perf_counter()

    @staticmethod
    def _stats(values: list[float]) -> dict[str, float]:
        if not values:
            return {"avg_ms": 0.0, "median_ms": 0.0, "p95_ms": 0.0, "p99_ms": 0.0, "max_ms": 0.0}
        ordered = sorted(values)
        pick = lambda p: ordered[min(len(ordered) - 1, int(len(ordered) * p))]
        return {
            "avg_ms": sum(values) / len(values),
            "median_ms": pick(0.5),
            "p95_ms": pick(0.95),
            "p99_ms": pick(0.99),
            "max_ms": max(values),
        }

    def summary(self, total_frames: int) -> dict[str, Any]:
        if not self.enabled:
            return {"enabled": False, "frames": 0}
        put_hist = {str(k): sum(1 for v in self.put_sizes_before.values() if v == k) for k in range(self.maxsize + 1)}
        after_put_hist = {str(k): sum(1 for v in self.put_sizes_after.values() if v == k) for k in range(self.maxsize + 1)}
        after_get_hist = {str(k): sum(1 for v in self.get_sizes_after.values() if v == k) for k in range(self.maxsize + 1)}
        return {
            "enabled": True,
            "frames": total_frames,
            "queue_depth": self.maxsize,
            "queue_size_before_put_histogram": put_hist,
            "queue_size_after_put_histogram": after_put_hist,
            "queue_size_after_get_histogram": after_get_hist,
            "producer_blocked_frames": self.put_full_frames,
            "producer_blocked_fraction": self.put_full_frames / max(1, len(self.put_sizes_before)),
            "producer_block": self._stats(self.put_block_ms),
            "consumer_blocked_frames": self.get_empty_frames,
            "consumer_blocked_fraction": self.get_empty_frames / max(1, len(self.get_sizes_after)),
            "consumer_block": self._stats(self.get_block_ms),
            "queue_full_frames": self.put_full_frames,
            "queue_full_fraction": self.put_full_frames / max(1, len(self.put_sizes_before)),
            "queue_empty_frames": self.get_empty_frames,
            "queue_empty_fraction": self.get_empty_frames / max(1, len(self.get_sizes_after)),
            "representative_frames": {str(k): self.events[k] for k in sorted(self.events) if k in {0, 1, 2, 30, 100, 300, 500, 750, 900, 1130}},
        }


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


# ETAP 3J: production default for AMD_ABOVE_SPARSE_COMPOSE (default OFF).
_ABOVE_SPARSE_COMPOSE_DEFAULT = False


def _resolve_above_sparse_compose() -> bool:
    """Resolve ``AMD_ABOVE_SPARSE_COMPOSE`` feature flag (0 = OFF, 1 = ON)."""
    return _env_flag("AMD_ABOVE_SPARSE_COMPOSE", _ABOVE_SPARSE_COMPOSE_DEFAULT)


# ETAP 10Q/10R: production default for AMD_ABOVE_DIRTY_MODE.
#   SCAN      = legacy alpha-scan path (candidate crop -> alpha scan ->
#               tight crop -> tobytes).  Complete fallback, always available.
#   CANDIDATE = candidate crop -> tobytes (skips alpha scan + final crop).
#               Env-opt-in DIAGNOSTIC ONLY: ETAP 10Q proved it is NOT
#               production-safe — the larger uploaded rect grows
#               ClearPreviousAboveMap's erase region and the final raster
#               differs from SCAN.
#   EXACT     = ETAP 10R fast exact tight-bbox path (Variant A): uploads the
#               exact SCAN tight region computed from propagated alpha-tight
#               widget bboxes, with a per-cluster SCAN fallback.
#               Production default after ETAP 10R: region parity PASS, final
#               GPU parity PASS (120/120 frames byte-identical), ghosting PASS,
#               map-underneath PASS, frame accounting PASS.  Dirty-path saving
#               measured ~0.5 ms/frame (modest; see RAPORT 10R).
_ABOVE_DIRTY_MODE_DEFAULT = "EXACT"


def _resolve_above_dirty_mode() -> str:
    """Resolve ``AMD_ABOVE_DIRTY_MODE`` with a SCAN fallback for unknown values.

    Supported: ``SCAN`` (legacy baseline), ``CANDIDATE`` (env-opt-in
    diagnostic — ETAP 10Q final-parity FAILED) and ``EXACT`` (ETAP 10R fast
    exact tight-bbox path).  An unknown value fails safe to ``SCAN`` with a
    single diagnostic warning.
    """
    raw = os.environ.get("AMD_ABOVE_DIRTY_MODE")
    if raw is None:
        return _ABOVE_DIRTY_MODE_DEFAULT
    mode = raw.strip().upper()
    if mode in ("SCAN", "CANDIDATE", "EXACT"):
        return mode
    print(
        f"[AMD NATIVE D3D11] WARNING: unknown AMD_ABOVE_DIRTY_MODE={raw!r}; "
        "falling back to SCAN.",
        flush=True,
    )
    return "SCAN"


# ETAP 10S/10U: production default for AMD_ABOVE_UPLOAD_BUFFER_MODE.
#   COPY   = historical path: full memcpy into a fresh ctypes buffer via
#            from_buffer_copy before the native call.  Safe fallback.
#   DIRECT = zero-copy pointer into the immutable Python bytes payload
#            (ctypes.c_char_p is O(1), no copy).  Safe because the native
#            UpdateAboveRegion -> UpdateSubresource copies the data
#            synchronously before returning (verified in
#            d3d11_vp_pipeline.cpp), so the pointer only needs to live for
#            the duration of the call (r_bytes is referenced throughout).
_ABOVE_UPLOAD_BUFFER_MODE_DEFAULT = "DIRECT"


def _resolve_above_upload_buffer_mode() -> str:
    """Resolve ``AMD_ABOVE_UPLOAD_BUFFER_MODE`` (COPY | DIRECT), COPY fallback."""
    raw = os.environ.get("AMD_ABOVE_UPLOAD_BUFFER_MODE")
    if raw is None:
        return _ABOVE_UPLOAD_BUFFER_MODE_DEFAULT
    mode = raw.strip().upper()
    if mode in ("COPY", "DIRECT"):
        return mode
    print(
        f"[AMD NATIVE D3D11] WARNING: unknown AMD_ABOVE_UPLOAD_BUFFER_MODE={raw!r}; "
        "falling back to COPY.",
        flush=True,
    )
    return "COPY"


# ETAP 3E/3F: AMD_ABOVE_MULTI_RECT
# 0           = Single Union Mode (legacy reference ONE UNION RECT)
# 1 (default) = Cost-aware Bounded Multi-Rect Planner (production default since ETAP 3F)
_ABOVE_MULTI_RECT_DEFAULT = 1

# ETAP 3H: AMD_ABOVE_FINE_DIRTY
# 0 (default) = Full-Widget Multi-Rect (production baseline)
# 1           = Fine-Grained Retained Dynamic Regions (experimental ETAP 3H)
_ABOVE_FINE_DIRTY_DEFAULT = 0


def _resolve_above_multi_rect() -> bool:
    """Resolve ``AMD_ABOVE_MULTI_RECT`` (0 = Single Union, 1 = Multi-Rect), default 1 (ON)."""
    raw = os.environ.get("AMD_ABOVE_MULTI_RECT")
    if raw is None:
        return bool(_ABOVE_MULTI_RECT_DEFAULT)
    return str(raw).strip().lower() in ("1", "true", "yes", "on")


def _resolve_above_fine_dirty() -> bool:
    """Resolve ``AMD_ABOVE_FINE_DIRTY`` (0 = Full-Widget Multi-Rect, 1 = Fine-Grained Retained Dirty), default 0 (OFF)."""
    raw = os.environ.get("AMD_ABOVE_FINE_DIRTY")
    if raw is None:
        return bool(_ABOVE_FINE_DIRTY_DEFAULT)
    return str(raw).strip().lower() in ("1", "true", "yes", "on")


def _above_region_pointer(r_bytes: bytes, mode: str):
    """ETAP 10S: build the pointer handed to ``telem_amd_update_above_region``.

    ``COPY``   — historical: full memcpy into a fresh ctypes buffer.
    ``DIRECT`` — zero-copy pointer into the immutable Python ``bytes`` payload
                 (``c_char_p`` is O(1) and does not copy; embedded NUL bytes
                 are just data because the native call uses the explicit
                 ``width*height*4`` length, not a C string).  The caller must
                 keep ``r_bytes`` referenced for the duration of the native
                 call, which the upload loop does.
    """
    if mode == "DIRECT":
        return ctypes.cast(ctypes.c_char_p(r_bytes), ctypes.POINTER(ctypes.c_uint8))
    return (ctypes.c_uint8 * len(r_bytes)).from_buffer_copy(r_bytes)


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


def _sync_frame_accounting_summary(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Summarize the mutually-exclusive SYNC production-frame parent."""
    if not records:
        return {"enabled": False, "frames": 0}
    parents = [float(row["parent_ms"]) for row in records]
    stage_names = sorted({name for row in records for name in row["stages"]})
    stage_values = {
        name: [float(row["stages"].get(name, 0.0)) for row in records]
        for name in stage_names
    }
    sums = [sum(values[i] for values in stage_values.values()) for i in range(len(records))]
    residual = [parents[i] - sums[i] for i in range(len(records))]
    parent_avg = statistics.fmean(parents)
    sum_avg = statistics.fmean(sums)
    return {
        "enabled": True,
        "frames": len(records),
        "frame_total_ms": _timing_summary(parents),
        "children_sum_ms": _timing_summary(sums),
        "stages": {name: _timing_summary(values) for name, values in stage_values.items()},
        "residual_other_ms": _timing_summary(residual),
        "parent_child_error_pct_avg": abs(parent_avg - sum_avg) / parent_avg * 100.0 if parent_avg else 0.0,
        "method": "one SYNC parent from before CPU preparation through normal synchronous native/output handling; children are sequential wall intervals",
    }


def _exclusive_timing_accounting(
    parent: list[float], children: dict[str, list[float]], residual_name: str | None = None
) -> dict[str, Any]:
    """Summarize same-frame child buckets plus explicit residual/overlap error."""
    n = len(parent)
    if not n:
        return {"frames": 0, "parent": {}, "children_sum": {}, "error": {}}
    sums = []
    child_avgs: dict[str, float] = {}
    for i in range(n):
        total = 0.0
        for name, values in children.items():
            value = float(values[i]) if i < len(values) else 0.0
            total += value
            child_avgs[name] = child_avgs.get(name, 0.0) + value
        if residual_name is not None:
            residual = float(parent[i]) - total
            total += residual
            child_avgs[residual_name] = child_avgs.get(residual_name, 0.0) + residual
        sums.append(total)
    for name in child_avgs:
        child_avgs[name] /= n
    errors = [sums[i] - float(parent[i]) for i in range(n)]
    parent_avg = statistics.fmean(parent)
    sum_avg = statistics.fmean(sums)
    return {
        "frames": n,
        "parent": {"avg_ms": parent_avg, "median_ms": statistics.median(parent)},
        "children_sum": {"avg_ms": sum_avg, "median_ms": statistics.median(sums), "children_avg_ms": child_avgs},
        "error": {
            "avg_ms": statistics.fmean(errors),
            "median_ms": statistics.median(errors),
            "pct_of_parent_avg": (abs(sum_avg - parent_avg) / parent_avg * 100.0) if parent_avg else 0.0,
            "max_abs_ms": max(abs(value) for value in errors),
        },
    }


def _production_above_accounting(summary: dict[str, Any]) -> dict[str, Any]:
    totals = summary.get("totals", {}) if summary.get("enabled") else {}
    parent_entry = totals.get("above.compose_total", {})
    calls = float(parent_entry.get("calls", 0.0))
    parent = float(parent_entry.get("total_ms", 0.0)) / calls if calls else 0.0
    children: dict[str, float] = {}
    for key, entry in totals.items():
        if key.startswith("above.widget.") or key == "above.custom_text_loop":
            count = float(entry.get("calls", 0.0))
            children[key.removeprefix("above.")] = (
                float(entry.get("total_ms", 0.0)) / count if count else 0.0
            )
    child_sum = sum(children.values())
    children["other_compose_bookkeeping"] = parent - child_sum
    child_sum = sum(children.values())
    error = abs(parent - child_sum) / parent * 100.0 if parent else 0.0
    return {
        "parent": {"avg_ms": parent, "calls": calls},
        "children_sum": {"avg_ms": child_sum, "children_avg_ms": children},
        "error": {"pct_of_parent": error, "other_compose_bookkeeping_ms": children["other_compose_bookkeeping"]},
        "method": "actual compose_overlay(map_above_layout) total minus explicitly timed widget/custom buckets; residual is exclusive compositor clear/layout/finalization bucket",
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
    video_timeline: Optional[Any] = None,
    amd_decode_mode: Optional[str] = None,
) -> bool:
    """Execute production native AMD D3D11 + AMF video export pipeline via telem_amd_native.dll."""
    # The GUI starts export on a worker thread while its editable layout remains
    # reachable by the UI.  Snapshot it once so rendering and the ETAP 5B
    # dependency plan are immutable for the whole export.
    layout = copy.deepcopy(layout)
    if video_timeline is not None and getattr(video_timeline, "clip_count", 0) > 0:
        per_clip_requested_frames = video_timeline.output_frame_counts(target_fps)
        total_frames = max(1, sum(per_clip_requested_frames))
        duration_s = total_frames / target_fps
    else:
        total_frames = max(1, math.ceil(duration_s * target_fps))
        per_clip_requested_frames = [total_frames]
    from src.render_progress import RenderProgressTracker
    progress_tracker = RenderProgressTracker(total_frames, on_render_progress, target_fps=target_fps)
    if video_timeline is not None and getattr(video_timeline, "clip_count", 0) > 0:
        native_clip_paths = [str(clip.path) for clip in video_timeline.clips]
    elif isinstance(input_files, (list, tuple)):
        native_clip_paths = [str(path) for path in input_files]
    else:
        native_clip_paths = [str(input_files)]
    input_file_str = str(Path(native_clip_paths[0]).resolve())
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
    bottleneck_proof_enabled = _env_flag("TELEM_AMD_BOTTLENECK_PROOF", False)
    if bottleneck_proof_enabled:
        frame_trace_enabled = True
        print("[AMD NATIVE D3D11] TELEM_AMD_BOTTLENECK_PROOF: ON (bottleneck audit instrumentation active)", flush=True)
    # ── AMD RENDER PATH AUDIT (temporary diagnostic instrumentation) ──
    # AMD_AUDIT_ALLOCS=1 adds cheap per-frame allocation counters
    # (sys.getallocatedblocks + tracemalloc current bytes) to the producer and
    # consumer so the audit report can quantify per-frame allocation pressure.
    # Disabled by default; remove together with the AMD render-path audit.
    audit_allocs_enabled = _env_flag("AMD_AUDIT_ALLOCS", False)
    # ── AMD RENDER PATH AUDIT 2 (temporary diagnostic instrumentation) ──
    # AMD_FRAME_TRACE=1 records a full per-frame wall-clock accounting (frame
    # total, producer children, consumer children, inter-frame gaps) to a CSV
    # next to the profile.  AMD_CHART_TRACE=1 logs the GPU_SPLIT chart decision
    # for HR/Cadence (see _chart_gpu_layout_safe).  Both disabled by default.
    frame_trace_enabled = _env_flag("AMD_FRAME_TRACE", False)
    chart_trace_enabled = _env_flag("AMD_CHART_TRACE", False)
    # ── ETAP 1A: Feature flag for after-map chart capture (diagnostic in 1A, default OFF) ──
    after_map_chart_capture_diag = _env_flag("AMD_AFTER_MAP_CHART_CAPTURE_DIAG", False)
    if after_map_chart_capture_diag:
        print("[AMD NATIVE D3D11] AMD_AFTER_MAP_CHART_CAPTURE_DIAG: ON (diagnostic after-map chart capture active; native after-map blend: NO)", flush=True)
    # ── ETAP 1B: Feature flag for native AFTER-MAP GPU_SPLIT charts (default ON) ──
    after_map_chart_gpu = _env_flag("AMD_AFTER_MAP_CHART_GPU", True)
    if after_map_chart_gpu:
        print(f"[AMD NATIVE D3D11] AMD_AFTER_MAP_CHART_GPU: ON ({'env' if 'AMD_AFTER_MAP_CHART_GPU' in os.environ else 'default'}; native after-map chart GPU_SPLIT active)", flush=True)
    else:
        print(f"[AMD NATIVE D3D11] AMD_AFTER_MAP_CHART_GPU: OFF ({'env' if 'AMD_AFTER_MAP_CHART_GPU' in os.environ else 'default'}; after-map charts CPU_REFERENCE)", flush=True)
    # ── ETAP 2A/2D: Feature flag for native AFTER-MAP GPU gauge (default ON) ──
    # When ON, the speed gauge (fit_enhanced_speed_text) is captured from the
    # map_above_layout (above-map compositor) and blended by the native
    # BlendGauge pass AFTER the map and BlendAboveMap — matching v10 Z-order.
    # When OFF, the gauge stays in above_compose (CPU_REFERENCE).
    after_map_gauge_gpu = _env_flag("AMD_AFTER_MAP_GAUGE_GPU", True)
    if after_map_gauge_gpu:
        print(f"[AMD NATIVE D3D11] AMD_AFTER_MAP_GAUGE_GPU: ON ({'env' if 'AMD_AFTER_MAP_GAUGE_GPU' in os.environ else 'default'}; gauge AFTER-MAP GPU BlendGauge active)", flush=True)
    else:
        print(f"[AMD NATIVE D3D11] AMD_AFTER_MAP_GAUGE_GPU: OFF ({'env' if 'AMD_AFTER_MAP_GAUGE_GPU' in os.environ else 'default'}; gauge CPU_REFERENCE in above_compose)", flush=True)

    # ── ETAP 2B/2C: dynamic-region gauge transfer mode selection ─────────────
    # Transfer mode when AMD_AFTER_MAP_GAUGE_GPU enables the AFTER-MAP GPU
    # gauge (default ON since ETAP 2D; explicit AMD_AFTER_MAP_GAUGE_GPU=0
    # restores the legacy CPU gauge path):
    #   MANUAL_RECTS — AMD_GAUGE_DYNAMIC_RECTS="x,y,w,h;..." set explicitly
    #                  (ETAP 2B behavior; the env var wins over AUTO so manual
    #                  experiments stay reproducible).
    #   AUTO         — ETAP 2C: upload rectangles derived automatically from
    #                  renderer semantics (gauge.py reports needle/value-text
    #                  support bboxes + a style signature used as epoch key).
    #                  AMD_GAUGE_AUTO_REGIONS=0 disables AUTO -> FULL_TILE.
    #   FULL_TILE    — one full-tile upload per rendered frame (ETAP 2A
    #                  behavior; also the per-frame SAFE fallback whenever
    #                  AUTO cannot prove safety: unsupported widget kind,
    #                  rotation != 0, missing renderer info).
    # In ALL region modes the first frame of every epoch and every N-th frame
    # afterwards (AMD_GAUGE_FULL_REFRESH_N, default 120) performs a full-tile
    # resync upload.
    gauge_region_mode = "FULL_TILE"
    gauge_dynamic_rects: list[tuple[int, int, int, int]] = []
    _gauge_rects_raw = os.environ.get("AMD_GAUGE_DYNAMIC_RECTS", "").strip()
    if after_map_gauge_gpu and _gauge_rects_raw:
        try:
            for _part in _gauge_rects_raw.split(";"):
                _nums = [int(v) for v in _part.split(",")]
                if len(_nums) != 4 or any(v < 0 for v in _nums):
                    raise ValueError(f"bad rect {_part!r}")
                if _nums[2] == 0 or _nums[3] == 0:
                    raise ValueError(f"zero-size rect {_part!r}")
                gauge_dynamic_rects.append(tuple(_nums))
            if len(gauge_dynamic_rects) > 8:
                raise ValueError("too many rects (max 8)")
            gauge_region_mode = "MANUAL_RECTS"
        except ValueError as exc:
            print(
                "[AMD NATIVE D3D11] ERROR: AMD_GAUGE_DYNAMIC_RECTS parse "
                f"failed ({exc}); ignoring region config.",
                flush=True,
            )
            gauge_dynamic_rects = []
            gauge_region_mode = "FULL_TILE"
    if after_map_gauge_gpu and gauge_region_mode == "FULL_TILE":
        if _env_flag("AMD_GAUGE_AUTO_REGIONS", True):
            gauge_region_mode = "AUTO"
    gauge_full_refresh_n = max(1, int(os.environ.get("AMD_GAUGE_FULL_REFRESH_N", "120")))
    if gauge_region_mode == "MANUAL_RECTS":
        print(
            "[AMD NATIVE D3D11] AMD_GAUGE_DYNAMIC_RECTS: " + _gauge_rects_raw
            + f" (k={len(gauge_dynamic_rects)}; ETAP 2B manual region transfer"
            f" active, full refresh every {gauge_full_refresh_n} frames)",
            flush=True,
        )
    elif gauge_region_mode == "AUTO":
        print(
            "[AMD NATIVE D3D11] AMD_GAUGE_DYNAMIC_RECTS: <unset>"
            " (ETAP 2C AUTO regions derived from renderer semantics;"
            f" SAFE/FULL-TILE fallback, full refresh every {gauge_full_refresh_n} frames)",
            flush=True,
        )
    else:
        print(
            "[AMD NATIVE D3D11] AMD_GAUGE_DYNAMIC_RECTS: <unset>"
            " (full-tile gauge upload every frame; ETAP 2A behavior)",
            flush=True,
        )
    print(
        f"[AMD GAUGE GPU] mode={gauge_region_mode} rects="
        + (str(len(gauge_dynamic_rects))
           if gauge_region_mode == "MANUAL_RECTS" else "-")
        + " geometry=-"
        + f" full_refresh={gauge_full_refresh_n}",
        flush=True,
    )
    frame_trace_rows: list[dict[str, Any]] = []
    native_hud_mode = os.environ.get("AMD_NATIVE_HUD_MODE", "GPU_HUD").strip().upper()
    if native_hud_mode not in _AMD_HUD_MODES:
        print(
            "[AMD NATIVE D3D11] ERROR: AMD_NATIVE_HUD_MODE must be "
            "CPU_REFERENCE or GPU_HUD.",
            flush=True,
        )
        return False
    # Priority resolution (Requirement 8 & 11):
    # 1. explicit env override AMD_DECODE_MODE
    # 2. explicit setting from GUI / caller (amd_decode_mode)
    # 3. fallback GPU
    amd_decode_mode_env = os.environ.get("AMD_DECODE_MODE", "").strip().upper()
    gui_requested_cpu = amd_decode_mode is not None and str(amd_decode_mode).strip().upper() in {"CPU", "0"}
    requested_mode = "CPU" if gui_requested_cpu else "GPU"

    if amd_decode_mode_env in {"CPU", "0"}:
        resolved_decode_mode = "CPU"
        decode_source = "ENV"
    elif amd_decode_mode_env in {"GPU", "1"}:
        resolved_decode_mode = "GPU"
        decode_source = "ENV"
    elif amd_decode_mode is not None and str(amd_decode_mode).strip().upper() in {"CPU", "0"}:
        resolved_decode_mode = "CPU"
        decode_source = "GUI"
    elif amd_decode_mode is not None and str(amd_decode_mode).strip().upper() in {"GPU", "1"}:
        resolved_decode_mode = "GPU"
        decode_source = "GUI"
    else:
        resolved_decode_mode = "GPU"
        decode_source = "default"

    if resolved_decode_mode == "CPU":
        default_decode_mode = "GPU_HUD_CPU_DECODE_REFERENCE"
    else:
        default_decode_mode = "GPU_HUD_D3D11VA"
    native_decode_mode = os.environ.get(
        "AMD_NATIVE_DECODE_MODE", default_decode_mode
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
    # Requirement 9 & 11: Clean startup decode log
    backend_name = "D3D11VA" if use_d3d11va else "FFmpeg-P010"
    print(
        f"[AMD DECODE] requested={requested_mode} effective={resolved_decode_mode} "
        f"source={decode_source} backend={backend_name}",
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

    gpu_map_rotate_flag = _env_flag("AMD_GPU_MAP_ROTATE", True)
    map_source_reuse_enabled = _env_flag("AMD_MAP_SOURCE_REUSE", False)
    map_cfg = layout.get("indicators", {}).get("track_map", {})
    is_track_up = str(map_cfg.get("map_orientation", "north_up")).strip().lower() == "track_up"
    gpu_map_rotate = gpu_map_enabled and gpu_map_rotate_flag and is_track_up
    print(
        f"[AMD NATIVE D3D11] AMD_GPU_MAP_ROTATE: {1 if gpu_map_rotate else 0} "
        f"(flag={gpu_map_rotate_flag} [{'env' if 'AMD_GPU_MAP_ROTATE' in os.environ else 'default'}], track_up={is_track_up}) | "
        f"AMD_MAP_SOURCE_REUSE: {1 if map_source_reuse_enabled else 0}",
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

    # ── ETAP 2E: resolve the real gauge widget key for this layout ────────
    # The v10 hard-code (``fit_enhanced_speed_text``) misses user layouts that
    # attach ``form == "gauge"`` to another key (e.g. ``speed_text``), which
    # forced the AFTER-MAP gauge probe to report bbox=None and fall back to
    # CPU_REFERENCE while the gauge was still rendered on the CPU ABOVE layer.
    gauge_layout_key = _resolve_gauge_layout_key(layout)
    if gauge_layout_key != _GAUGE_KEY:
        print(
            f"[AMD NATIVE D3D11] Gauge widget key: {gauge_layout_key} "
            f"(layout-resolved; legacy default {_GAUGE_KEY})",
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

    # ── ETAP 2G/3I: GPU lean indicator dynamic transform ──────────────────
    # Production default since ETAP 3I (True/1). Explicit AMD_LEAN_GPU=0 restores CPU fallback.
    lean_gpu_flag = _env_flag("AMD_LEAN_GPU", True)
    lean_key = "lean_indicator"
    for _k, _cfg in layout.get("indicators", {}).items():
        if _k == "lean_indicator" or _cfg.get("form") == "lean":
            lean_key = _k
            break
    lean_in_layout = lean_key in layout.get("indicators", {}) and layout["indicators"][lean_key].get("enabled", True)
    lean_gpu_enabled = lean_gpu_flag and lean_in_layout and not cpu_reference_hud
    print(
        f"[AMD NATIVE D3D11] AMD_LEAN_GPU: {1 if lean_gpu_enabled else 0} "
        f"(flag={lean_gpu_flag} [{'env' if 'AMD_LEAN_GPU' in os.environ else 'default'}], "
        f"lean_in_layout={lean_in_layout}, key={lean_key})",
        flush=True,
    )

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

    # ── ETAP 10Q/10R: AMD ABOVE dirty-region mode ────────────────────
    # SCAN      = legacy path (candidate crop -> alpha scan -> tight crop
    #             -> tobytes).  Production default until ETAP 10R validates
    #             EXACT (region parity, final GPU parity, ghosting,
    #             map-underneath, frame accounting).
    # CANDIDATE = candidate crop -> tobytes (skips the local alpha scan and
    #             the tight final crop).  Env-opt-in DIAGNOSTIC ONLY: ETAP 10Q
    #             proved the larger uploaded rect grows ClearPreviousAboveMap's
    #             erase region and the final raster differs from SCAN.
    # EXACT     = ETAP 10R Variant A: uploads the exact SCAN tight region
    #             computed from propagated alpha-tight widget bboxes, with a
    #             per-cluster SCAN fallback.  Becomes the production default
    #             only after ETAP 10R validation (see _extract_exact_above_regions).
    above_dirty_mode = _resolve_above_dirty_mode()
    print(f"[AMD NATIVE D3D11] AMD_ABOVE_DIRTY_MODE: {above_dirty_mode}", flush=True)

    # ── ETAP 10S: ABOVE upload buffer mode (COPY fallback | DIRECT zero-copy) ──
    above_upload_buffer_mode = _resolve_above_upload_buffer_mode()
    print(
        f"[AMD NATIVE D3D11] AMD_ABOVE_UPLOAD_BUFFER_MODE: {above_upload_buffer_mode}",
        flush=True,
    )

    # ── ETAP 3E: ABOVE multi-rect dirty upload mode (0 = Single Union, 1 = Multi-Rect) ──
    above_multi_rect_enabled = _resolve_above_multi_rect()
    above_multi_rect_max = int(os.environ.get("AMD_ABOVE_MULTI_RECT_MAX", "8"))
    print(
        f"[AMD NATIVE D3D11] AMD_ABOVE_MULTI_RECT: {1 if above_multi_rect_enabled else 0} "
        f"({'MULTI_RECT' if above_multi_rect_enabled else 'SINGLE_UNION'}, max_rects={above_multi_rect_max})",
        flush=True,
    )

    # ── ETAP 3H: ABOVE fine-grained retained dynamic dirty updates ──
    above_fine_dirty_enabled = _resolve_above_fine_dirty() and above_multi_rect_enabled
    print(
        f"[AMD NATIVE D3D11] AMD_ABOVE_FINE_DIRTY: {1 if above_fine_dirty_enabled else 0} "
        f"({'FINE_DIRTY_RETAINED' if above_fine_dirty_enabled else 'FULL_WIDGET_MULTI_RECT'})",
        flush=True,
    )

    # ── ETAP 3J: ABOVE sparse compositor mode ──
    above_sparse_compose_enabled = _resolve_above_sparse_compose()
    print(
        f"[AMD NATIVE D3D11] AMD_ABOVE_SPARSE_COMPOSE: {1 if above_sparse_compose_enabled else 0}",
        flush=True,
    )

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
    pipeline_mode_resolved = os.getenv("AMD_CPU_GPU_PIPELINE", "ASYNC").upper()
    if pipeline_mode_resolved not in ("ASYNC", "SYNC"):
        pipeline_mode_resolved = "ASYNC"
    q_depth_resolved = max(1, int(os.getenv("AMD_QUEUE_DEPTH", "2"))) if pipeline_mode_resolved == "ASYNC" else 0
    vp_state_env = os.getenv("AMD_VP_STATE_MODE", "REFERENCE").upper()
    vp_pool_env = os.getenv("AMD_VP_POOL_SIZE", "8")
    amf_query_env = os.getenv("AMD_AMF_QUERY_MODE", "REFERENCE").upper()
    map_align_env = os.getenv("AMD_MAP_ALIGN", "16")
    nv12_comp_env = os.getenv("AMD_NV12_COMPOSITOR", "1")

    print("\n=== AMD REAL PRODUCTION EFFECTIVE CONFIG ===", flush=True)
    print(f"  CPU_GPU_PIPELINE = {pipeline_mode_resolved}", flush=True)
    print(f"  DECODE_MODE      = {'CPU (FFmpeg P010)' if not use_d3d11va else 'GPU (D3D11VA / VCN)'}", flush=True)
    print(f"  QUEUE_DEPTH      = {q_depth_resolved}", flush=True)
    print(f"  VP_STATE         = {vp_state_env}", flush=True)
    print(f"  VP_POOL          = {vp_pool_env}", flush=True)
    print(f"  AMF_QUERY        = {amf_query_env}", flush=True)
    print(f"  MAP_PATH         = {'GPU' if gpu_map_enabled else 'CPU_REFERENCE'}", flush=True)
    print(f"  MAP_ALIGN        = {map_align_env}", flush=True)
    print(f"  GAUGE_GPU        = {1 if after_map_gauge_gpu else 0} ({gauge_region_mode})", flush=True)
    print(f"  CHART_GPU        = {1 if after_map_chart_gpu else 0} ({requested_chart_path})", flush=True)
    print(f"  LEAN_GPU         = {1 if lean_gpu_enabled else 0}", flush=True)
    print(f"  HUD_MODE         = {native_hud_mode}", flush=True)
    print(f"  HUD_UPLOAD       = {hud_upload_mode}", flush=True)
    print(f"  NV12_COMPOSITOR  = {'FUSED' if nv12_comp_env == '1' else 'REFERENCE'}", flush=True)
    print(f"  PROFILING        = {1 if profiling_enabled else 0}", flush=True)
    print("============================================\n", flush=True)

    input_probe = _probe_video_summary(ffmpeg_exe, input_file_str)
    source_frames = _stream_frame_count(input_probe, "video")
    source_rotation = _probe_rotation_degrees(input_probe)

    # 1. Locate and Load telem_amd_native.dll
    repo_root = Path(__file__).resolve().parents[2]
    dll_override = os.environ.get("TELEM_AMD_NATIVE_DLL", "").strip()
    dll_path = str(
        Path(dll_override).resolve() if dll_override else
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

    if hasattr(native_dll, "telem_amd_update_video_frame_p010"):
        native_dll.telem_amd_update_video_frame_p010.restype = c_int
        native_dll.telem_amd_update_video_frame_p010.argtypes = [
            c_void_p, POINTER(c_uint8), c_uint, c_uint, c_uint, POINTER(ctypes.c_double)
        ]

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

    if hasattr(native_dll, "telem_amd_drain_amf"):
        native_dll.telem_amd_drain_amf.restype = c_int
        native_dll.telem_amd_drain_amf.argtypes = [c_void_p]

    if hasattr(native_dll, "telem_amd_get_queue_stats"):
        native_dll.telem_amd_get_queue_stats.restype = None
        native_dll.telem_amd_get_queue_stats.argtypes = [
            c_void_p,
            POINTER(c_uint64), POINTER(c_uint64), POINTER(c_uint64), POINTER(c_uint64),
            POINTER(c_uint64), POINTER(c_uint64), POINTER(c_uint64), POINTER(c_uint64),
            POINTER(ctypes.c_double),
        ]

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
        c_void_p, c_void_p, c_uint, c_uint, c_uint,
        POINTER(c_uint64), POINTER(c_int),
    ]

    native_dll.telem_amd_set_map_rotate_mode.restype = c_int
    native_dll.telem_amd_set_map_rotate_mode.argtypes = [c_void_p, c_int]

    native_dll.telem_amd_set_map_heading.restype = c_int
    native_dll.telem_amd_set_map_heading.argtypes = [c_void_p, c_float]

    native_dll.telem_amd_update_map_marker.restype = c_int
    native_dll.telem_amd_update_map_marker.argtypes = [
        c_void_p, ctypes.c_char_p, c_uint, c_uint, c_uint, c_uint, c_uint,
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
    if hasattr(native_dll, "telem_amd_update_above_regions_batch"):
        native_dll.telem_amd_update_above_regions_batch.restype = c_int
        native_dll.telem_amd_update_above_regions_batch.argtypes = [
            c_void_p, POINTER(c_void_p), c_uint, POINTER(HUDDirtyRect), c_uint,
        ]
    if hasattr(native_dll, "telem_amd_get_above_region_timings"):
        native_dll.telem_amd_get_above_region_timings.restype = None
        native_dll.telem_amd_get_above_region_timings.argtypes = [
            c_void_p, POINTER(c_double), POINTER(c_double), POINTER(c_uint),
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

    # ── ETAP 1B — GPU AFTER-MAP chart compositing ───────────────────────
    native_dll.telem_amd_set_after_map_chart_mode.restype = c_int
    native_dll.telem_amd_set_after_map_chart_mode.argtypes = [c_void_p, c_int]

    native_dll.telem_amd_update_after_map_chart_static.restype = c_int
    native_dll.telem_amd_update_after_map_chart_static.argtypes = [
        c_void_p, c_int, ctypes.c_char_p, c_uint, c_uint, c_uint,
        c_uint, c_uint, POINTER(c_uint64), POINTER(c_int),
    ]

    native_dll.telem_amd_update_after_map_chart_dynamic.restype = c_int
    native_dll.telem_amd_update_after_map_chart_dynamic.argtypes = [
        c_void_p, c_int, c_int, ctypes.c_char_p, c_uint, c_uint, c_uint,
        c_uint, c_uint, POINTER(c_uint64),
    ]

    native_dll.telem_amd_get_after_map_chart_stats.restype = None
    native_dll.telem_amd_get_after_map_chart_stats.argtypes = [
        c_void_p, POINTER(c_uint64), POINTER(c_uint64), POINTER(c_uint64),
        POINTER(c_double), POINTER(c_uint64), POINTER(c_uint64),
        POINTER(c_uint64), POINTER(c_uint64),
    ]

    # ── ETAP 5L — GPU gauge compositing ────────────────────────────────
    native_dll.telem_amd_set_gauge_mode.restype = c_int
    native_dll.telem_amd_set_gauge_mode.argtypes = [c_void_p, c_int]

    # ── ETAP 2A — gauge pass placement (1 = AFTER-MAP, 0 = legacy BEFORE-MAP) ──
    native_dll.telem_amd_set_gauge_after_map.restype = c_int
    native_dll.telem_amd_set_gauge_after_map.argtypes = [c_void_p, c_int]

    # ── ETAP 2A FIX — start-of-frame clears on demand (before HUD upload) ──
    native_dll.telem_amd_run_early_clears.restype = c_int
    native_dll.telem_amd_run_early_clears.argtypes = [c_void_p]

    native_dll.telem_amd_update_gauge.restype = c_int
    native_dll.telem_amd_update_gauge.argtypes = [
        c_void_p, c_void_p, c_uint, c_uint, c_uint,
        c_uint, c_uint, POINTER(c_uint64), POINTER(c_int),
    ]

    # ── ETAP 2B — partial gauge texture update (dynamic sub-region) ──
    native_dll.telem_amd_update_gauge_region.restype = c_int
    native_dll.telem_amd_update_gauge_region.argtypes = [
        c_void_p, c_void_p,
        c_uint, c_uint, c_uint, c_uint, c_uint,
        c_uint, c_uint, c_uint, c_uint,
        POINTER(c_uint64), POINTER(c_int),
    ]

    native_dll.telem_amd_get_gauge_stats.restype = None
    native_dll.telem_amd_get_gauge_stats.argtypes = [
        c_void_p, POINTER(c_uint64), POINTER(c_uint64),
        POINTER(c_double), POINTER(c_double), POINTER(c_uint64),
    ]

    # ── ETAP 2G — GPU lean indicator compositing ───────────────────────
    native_dll.telem_amd_set_lean_gpu_mode.restype = c_int
    native_dll.telem_amd_set_lean_gpu_mode.argtypes = [c_void_p, c_int]

    native_dll.telem_amd_update_lean_static_texture.restype = c_int
    native_dll.telem_amd_update_lean_static_texture.argtypes = [
        c_void_p, ctypes.c_char_p, c_uint, c_uint, c_uint,
        POINTER(c_uint64), POINTER(c_int),
    ]

    native_dll.telem_amd_set_lean_transform.restype = c_int
    native_dll.telem_amd_set_lean_transform.argtypes = [
        c_void_p, c_float, c_float, c_float, c_float, c_float,
        c_uint, c_uint, c_uint, c_uint,
    ]

    native_dll.telem_amd_get_lean_stats.restype = None
    native_dll.telem_amd_get_lean_stats.argtypes = [
        c_void_p, POINTER(c_uint64), POINTER(c_uint64), POINTER(c_double),
    ]

    native_dll.telem_amd_set_source_rotation.restype = c_int
    native_dll.telem_amd_set_source_rotation.argtypes = [c_void_p, c_uint]

    native_dll.telem_amd_set_decode_mode.restype = c_int
    native_dll.telem_amd_set_decode_mode.argtypes = [c_void_p, c_int]

    native_switch_source = getattr(native_dll, "telem_amd_switch_source", None)
    if video_timeline is not None and getattr(video_timeline, "clip_count", 0) > 1:
        if native_switch_source is None:
            print("[AMD NATIVE D3D11] Multi-file ABI unavailable; returning controlled fallback.", flush=True)
            return False
        native_switch_source.restype = c_int
        native_switch_source.argtypes = [c_void_p, ctypes.c_wchar_p]
    native_seek_source = getattr(native_dll, "telem_amd_seek_source", None)
    range_seek_required = any(
        float(getattr(clip, "local_start_s", 0.0) or 0.0) > 0.0
        for clip in getattr(video_timeline, "clips", [])
    )
    if range_seek_required:
        if native_seek_source is None:
            print("[AMD NATIVE D3D11] Range-seek ABI unavailable.", flush=True)
            return False
        native_seek_source.restype = c_int
        native_seek_source.argtypes = [c_void_p, ctypes.c_int64]
        native_discard_video_sample = getattr(
            native_dll, "telem_amd_discard_video_sample", None
        )
        if native_discard_video_sample is None:
            print("[AMD NATIVE D3D11] Range-discard ABI unavailable.", flush=True)
            return False
        native_discard_video_sample.restype = c_int
        native_discard_video_sample.argtypes = [c_void_p]
    else:
        native_discard_video_sample = None

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
        _init_t0 = time.perf_counter()
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
        progress_tracker.hud_work(1, 8, "worker cache and fonts")
        print(f"[HUD] worker initialization={time.perf_counter() - _init_t0:.3f}s", flush=True)
    else:
        progress_tracker.hud_work(1, 8, "HUD disabled")


    fps_rate = Fraction(target_fps).limit_denominator(100_000)
    fps_num = fps_rate.numerator
    fps_den = fps_rate.denominator

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
    # ── Single & Multi-File Direct Live MP4 Mux Setup ────────────────────
    # Eliminates buffering the full temporary .h265 bitstream on disk.
    is_multi_file = video_timeline is not None and getattr(video_timeline, "clip_count", 0) > 1
    direct_mux_enabled = _env_flag("AMD_DIRECT_MUX", True) and (amf_mode not in ("SUBMIT_NO_MUX", "BYPASS"))
    direct_mux_completed = False
    audio_concat_path: Optional[Path] = None

    proc_mux: subprocess.Popen | None = None
    h_pipe: Any = None
    pump_thread: threading.Thread | None = None
    stderr_thread: threading.Thread | None = None
    mux_stderr_lines: list[bytes] = []
    mux_pump_error: Optional[str] = None
    mux_pump_stats: dict[str, int] = {"bytes": 0, "chunks": 0}
    output_part_str = output_file_str + ".part"
    native_out_target = output_file_str

    if direct_mux_enabled:
        if os.path.exists(output_part_str):
            try:
                os.remove(output_part_str)
            except OSError:
                pass
        pipe_token = uuid.uuid4().hex[:8]
        pipe_base = rf"\\.\pipe\telem_amf_{os.getpid()}_{pipe_token}"
        pipe_server_name = pipe_base + ".h265"
        kernel32 = ctypes.windll.kernel32
        h_pipe = kernel32.CreateNamedPipeW(
            pipe_server_name,
            0x00000001,  # PIPE_ACCESS_INBOUND
            0x00000000,  # PIPE_TYPE_BYTE | PIPE_WAIT
            1,
            4 * 1024 * 1024,  # 4MB buffer
            4 * 1024 * 1024,
            0,
            None,
        )
        if h_pipe == -1 or h_pipe == 0:
            print(f"[AMD NATIVE D3D11] WARNING: Failed to create Named Pipe ({kernel32.GetLastError()}), falling back to file mux.", flush=True)
            direct_mux_enabled = False
            h_pipe = None
        else:
            if is_multi_file:
                audio_concat_path = Path(output_file_str).with_suffix(".audio.concat.txt")
                with audio_concat_path.open("w", encoding="utf-8", newline="\n") as concat_file:
                    for clip in video_timeline.clips:
                        concat_file.write("file '" + str(clip.path).replace("'", "'\\''") + "'\n")
                        local_start = float(getattr(clip, "local_start_s", 0.0) or 0.0)
                        if local_start > 0.0:
                            concat_file.write(f"inpoint {local_start:.9f}\n")
                        local_end = float(getattr(clip, "local_end_s", clip.duration_s))
                        source_duration = float(getattr(clip, "source_duration_s", 0.0) or 0.0)
                        if source_duration <= 0.0 or local_end < source_duration - 1e-6:
                            concat_file.write(f"outpoint {local_end:.9f}\n")
                audio_args = ["-f", "concat", "-safe", "0", "-i", str(audio_concat_path)]
            else:
                audio_args: list[str] = ["-i", input_file_str]
                if video_timeline is not None and getattr(video_timeline, "clip_count", 0) > 0:
                    clip0_local_start = float(getattr(video_timeline.clips[0], "local_start_s", 0.0) or 0.0)
                    if clip0_local_start > 0.0:
                        audio_args = ["-ss", f"{clip0_local_start:.6f}", "-i", input_file_str]

            cmd_live_mux = [
                ffmpeg_exe, "-y",
                "-f", "hevc",
                "-r", f"{fps_num}/{fps_den}",
                "-i", "-",
                *audio_args,
                "-map", "0:v", "-map", "1:a?",
                "-t", f"{duration_s:.6f}",
                "-c:v", "copy",
                "-c:a", "copy",
                "-f", "mp4",
                output_part_str,
            ]
            try:
                proc_mux = subprocess.Popen(
                    cmd_live_mux,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                )
            except Exception as e:
                print(f"[AMD NATIVE D3D11] WARNING: Failed to launch FFmpeg live muxer ({e}), falling back to file mux.", flush=True)
                direct_mux_enabled = False
                kernel32.CloseHandle(h_pipe)
                h_pipe = None
                proc_mux = None

        if direct_mux_enabled and proc_mux is not None and h_pipe is not None:
            native_out_target = pipe_base
            mode_str = "multi" if is_multi_file else "single"
            clip_count_str = str(getattr(video_timeline, "clip_count", 1) if video_timeline else 1)
            audio_mode_str = "concat" if is_multi_file else "source"
            print(f"[AMD DIRECT MUX] mode={mode_str} clips={clip_count_str} video=pipe audio={audio_mode_str} output=.part", flush=True)
            print(f"[AMD NATIVE D3D11] DIRECT MP4 MUX:      ENABLED (live streaming -> {Path(output_part_str).name})", flush=True)

            def _mux_stderr_reader():
                try:
                    if proc_mux and proc_mux.stderr:
                        for line in proc_mux.stderr:
                            mux_stderr_lines.append(line)
                except Exception:
                    pass

            stderr_thread = threading.Thread(target=_mux_stderr_reader, daemon=True)
            stderr_thread.start()

            def _mux_pump_worker():
                nonlocal mux_pump_error
                connected = kernel32.ConnectNamedPipe(h_pipe, None)
                if not connected:
                    err = kernel32.GetLastError()
                    if err != 535:  # ERROR_PIPE_CONNECTED
                        mux_pump_error = f"ConnectNamedPipe error: {err}"
                        return
                buf = ctypes.create_string_buffer(256 * 1024)
                bytes_read = wintypes.DWORD()
                try:
                    while True:
                        res = kernel32.ReadFile(h_pipe, buf, len(buf), ctypes.byref(bytes_read), None)
                        if not res or bytes_read.value == 0:
                            break
                        if proc_mux.poll() is not None and proc_mux.returncode != 0:
                            mux_pump_error = f"FFmpeg muxer exited prematurely with rc {proc_mux.returncode}"
                            break
                        proc_mux.stdin.write(buf.raw[:bytes_read.value])
                        mux_pump_stats["bytes"] += bytes_read.value
                        mux_pump_stats["chunks"] += 1
                except Exception as ex:
                    mux_pump_error = f"Pump exception: {ex}"
                finally:
                    try:
                        if proc_mux and proc_mux.stdin:
                            proc_mux.stdin.close()
                    except Exception:
                        pass
                    try:
                        if h_pipe is not None:
                            kernel32.CloseHandle(h_pipe)
                    except Exception:
                        pass

            pump_thread = threading.Thread(target=_mux_pump_worker, daemon=True)
            pump_thread.start()
        else:
            print("[AMD NATIVE D3D11] DIRECT MP4 MUX:      DISABLED (file finalize path)", flush=True)
    else:
        print("[AMD NATIVE D3D11] DIRECT MP4 MUX:      DISABLED (file finalize path)", flush=True)

    print("[AMD NATIVE D3D11] ===================================", flush=True)
    proc_dec: subprocess.Popen | None = None
    h_cpu_pipe: int | None = None
    p010_c_buf = None
    p010_buf_addr = None
    h_context = native_dll.telem_amd_create(
        input_file_str,
        native_out_target,
        video_width,
        video_height,
        fps_num,
        fps_den
    )

    if not h_context:
        print("[AMD NATIVE D3D11] ERROR: telem_amd_create returned NULL!", flush=True)
        print("AMD_NATIVE_D3D11 = FAIL", flush=True)
        if proc_mux is not None:
            try: proc_mux.kill()
            except Exception: pass
        if h_pipe is not None:
            try: kernel32.CloseHandle(h_pipe)
            except Exception: pass
        return False

    def _cleanup_native_resources() -> None:
        """P1-A FIX: Idempotent cleanup of native D3D11 context, decoder process, and direct mux."""
        nonlocal h_context, proc_dec, h_cpu_pipe
        if h_cpu_pipe is not None and h_cpu_pipe != -1 and h_cpu_pipe != 0:
            try:
                kernel32.CloseHandle(h_cpu_pipe)
            except Exception:
                pass
            h_cpu_pipe = None
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

    def _abort_direct_mux() -> None:
        nonlocal proc_mux, h_pipe, audio_concat_path
        if proc_mux is not None:
            if proc_mux.poll() is None:
                try:
                    proc_mux.kill()
                except Exception:
                    pass
            try:
                proc_mux.wait(timeout=2.0)
            except Exception:
                pass
            proc_mux = None
        if h_pipe is not None and h_pipe != -1 and h_pipe != 0:
            try:
                GENERIC_WRITE = 0x40000000
                OPEN_EXISTING = 3
                h_c = kernel32.CreateFileW(pipe_server_name, GENERIC_WRITE, 0, None, OPEN_EXISTING, 0, None)
                if h_c != -1 and h_c != 0:
                    kernel32.CloseHandle(h_c)
            except Exception:
                pass
            try:
                kernel32.CloseHandle(h_pipe)
            except Exception:
                pass
            h_pipe = None
        if os.path.exists(output_part_str):
            try:
                os.remove(output_part_str)
            except OSError:
                pass
        if audio_concat_path is not None and audio_concat_path.exists():
            try:
                audio_concat_path.unlink()
            except OSError:
                pass

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
        if gpu_map_rotate:
            native_dll.telem_amd_set_map_rotate_mode(h_context, 1)
            raw_map_w_cfg = s(map_cfg.get("size", 0.1), video_width)
            map_w_cfg = _quantize_map_val(int(raw_map_w_cfg), os.environ.get("AMD_MAP_ALIGN", "1"))
            render_plan = _map_render_plan(video_width, map_w_cfg, int(map_cfg.get("zoom", 16)))
            marker_style = str(map_cfg.get("map_marker_style", "dot")).strip().lower()
            marker_color = _parse_marker_color(map_cfg.get("marker_color", "#FFFFFF"))
            marker_radius = max(1, int(round(float(map_cfg.get("marker_size", 7)) * (2.0 ** render_plan["zoom_offset"]))))
            mkr_tile, mkr_rect = build_static_map_marker_tile(map_w_cfg, marker_radius, marker_style, marker_color)
            if mkr_tile is not None:
                mkr_bytes = mkr_tile.tobytes("raw", "RGBA")
                mx, my, mw, mh = mkr_rect
                native_dll.telem_amd_update_map_marker(h_context, mkr_bytes, mw, mh, mw * 4, mx, my)
        else:
            native_dll.telem_amd_set_map_rotate_mode(h_context, 0)

    # ── ETAP 5J / 5K: GPU chart compositing (0 = CPU_REFERENCE, 1 = GPU,
    # 2 = GPU_SPLIT) ───────────────────────────────────────────────────
    if not native_dll.telem_amd_set_chart_mode(h_context, chart_mode_value):
        print("[AMD NATIVE D3D11] ERROR: failed to configure GPU chart mode.", flush=True)
        _cleanup_native_resources()
        return False

    # ── ETAP 1B: GPU AFTER-MAP chart compositing (2 = GPU_SPLIT, 0 = CPU_REFERENCE) ─
    after_map_chart_mode_val = 2 if after_map_chart_gpu else 0
    if not native_dll.telem_amd_set_after_map_chart_mode(h_context, after_map_chart_mode_val):
        print("[AMD NATIVE D3D11] ERROR: failed to configure GPU after-map chart mode.", flush=True)
        _cleanup_native_resources()
        return False

    # ── ETAP 5L: GPU gauge compositing (1 = GPU, 0 = CPU_REFERENCE) ────
    if not native_dll.telem_amd_set_gauge_mode(h_context, 1 if gauge_gpu_requested else 0):
        print("[AMD NATIVE D3D11] ERROR: failed to configure GPU gauge mode.", flush=True)
        _cleanup_native_resources()
        return False

    # ── ETAP 2A: gauge pass placement (1 = AFTER-MAP experimental,
    #    0 = legacy BEFORE-MAP).  Default OFF keeps ETAP 5L semantics. ──
    if not native_dll.telem_amd_set_gauge_after_map(h_context, 1 if after_map_gauge_gpu else 0):
        print("[AMD NATIVE D3D11] ERROR: failed to configure gauge placement.", flush=True)
        _cleanup_native_resources()
        return False

    # ── ETAP 2G: GPU lean indicator dynamic transform (1 = GPU, 0 = CPU) ─
    if not native_dll.telem_amd_set_lean_gpu_mode(h_context, 1 if lean_gpu_enabled else 0):
        print("[AMD NATIVE D3D11] ERROR: failed to configure GPU lean mode.", flush=True)
        _cleanup_native_resources()
        return False
    # Keep the diagnostic CPU-HUD reporting path valid even when the GPU lean
    # path is disabled.  Previously lean_cfg was created only inside the
    # lean_gpu_enabled branch but referenced later by the shared diagnostics
    # closure, causing HUD_CPU to fail before its intended measurement.
    lean_cfg = layout.get("indicators", {}).get(lean_key, {})
    if lean_gpu_enabled:
        from src.indicators.lean import _load_lean_rotation_source, get_lean_gpu_transform_info
        _size_px = s(lean_cfg.get("size", 0.1), video_width)
        _g = max(32, int(_size_px))
        rot_src = _load_lean_rotation_source(lean_cfg, _g)
        if rot_src is not None:
            sprite_bytes = rot_src.graphic.tobytes("raw", "RGBA")
            uploaded_bytes = c_uint64(0)
            tex_created = c_int(0)
            native_dll.telem_amd_update_lean_static_texture(
                h_context,
                sprite_bytes,
                rot_src.gw, rot_src.gh, rot_src.gw * 4,
                byref(uploaded_bytes), byref(tex_created)
            )
            print(
                f"[AMD NATIVE D3D11] GPU lean static sprite uploaded: {rot_src.gw}x{rot_src.gh} "
                f"({uploaded_bytes.value} bytes, pivot={rot_src.pivot_px},{rot_src.pivot_py})",
                flush=True,
            )
        # Suppress CPU bike dynamic graphic rendering in all compose layouts
        for _l in (compose_layout, map_above_layout, semantic_layout):
            if _l is not None and "indicators" in _l:
                for _k, _c in _l["indicators"].items():
                    if _k == "lean_indicator" or _c.get("form") == "lean":
                        _c["_skip_dynamic_graphic"] = True

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

    if range_seek_required:
        initial_seek = int(round(
            float(video_timeline.clips[0].local_start_s) * 10_000_000
        ))
        if not native_seek_source(h_context, initial_seek):
            print("[AMD NATIVE D3D11] Initial source range seek failed.", flush=True)
            _cleanup_native_resources()
            return False
        pending_seek_target_100ns: int | None = initial_seek
    else:
        pending_seek_target_100ns = None

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
    # GUI phase-report: AMD native HUD initialization has started.
    progress_tracker.hud_work(0, 8, "native initialization")

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
        # ETAP 2B — gauge capture / diff / byte-rate samples
        "gauge_capture": [],
        "gauge_diff": [],
        "gauge_bytes_per_frame": [],
        "gauge_upload_calls": [],
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
        "above_upload_buffer_prepare": [],
        "above_tight_bbox_collect": [],
        "above_exact_union": [],
        "above_exact_crop": [],
        "region_pipeline_total": [],
        "python_control_total": [],
        "native_region_total": [],
        "update_subresource_cpu": [],
        "update_subresource_calls": [],
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
    seek_discarded_frames = 0
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
    # ETAP 10R EXACT counters (accumulated across frames for the profile).
    above_exact_counters: dict[str, Any] = {
        "clusters": 0,
        "fallback_clusters": 0,
        "fallback_reason": {},
    }
    above_exact_clusters_samples: list[int] = []
    above_scan_fallback_clusters_samples: list[int] = []
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
    sync_frame_accounting_enabled = _env_flag("AMD_SYNC_FRAME_ACCOUNTING", False)
    sync_frame_records: list[dict[str, Any]] = []
    sync_frame_current: dict[str, Any] | None = None

    def _sync_frame_mark(name: str) -> None:
        if not sync_frame_accounting_enabled or sync_frame_current is None:
            return
        now_ns = time.perf_counter_ns()
        elapsed_ms = (now_ns - sync_frame_current["last_ns"]) / 1_000_000.0
        sync_frame_current["stages"][name] = sync_frame_current["stages"].get(name, 0.0) + elapsed_ms
        sync_frame_current["last_ns"] = now_ns

    print(
        f"AMD_SYNC_FRAME_ACCOUNTING: {'ON' if sync_frame_accounting_enabled else 'OFF'}",
        flush=True,
    )

    queue_truth = _QueueTruth(_env_flag("AMD_5Q_QUEUE_DIAG", False))
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
    # ETAP 1A — BEFORE-MAP / AFTER-MAP chart classification & diagnostic capture
    before_map_chart_keys: set[str] = set()
    after_map_chart_keys: set[str] = set()
    all_layout_chart_keys: set[str] = set()
    for _ck in _CHART_GPU_SLOTS.keys():
        if _ck in layout.get("indicators", {}) and layout["indicators"][_ck].get("enabled", True):
            all_layout_chart_keys.add(_ck)

    if map_above_layout is not None:
        for _ck in all_layout_chart_keys:
            if _ck in map_above_layout.get("indicators", {}):
                after_map_chart_keys.add(_ck)
            else:
                before_map_chart_keys.add(_ck)
    else:
        before_map_chart_keys = set(all_layout_chart_keys)

    gpu_chart_keys_before_map: set[str] = set()
    gpu_chart_keys_after_map: set[str] = set()
    after_map_chart_static_uploaded: set[str] = set()
    after_map_captures_performed: int = 0
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
    # ETAP 2B: dynamic-region gauge transfer counters.
    gauge_upload_calls_total = 0
    gauge_full_upload_frames = 0
    gauge_region_upload_frames = 0
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

    # CPU decode path uses FFmpeg rawvideo P010 10-bit with a high-throughput Named Pipe.
    cmd_decode: list[str] | None = None
    frame_size = (video_width * video_height * 3) if not use_d3d11va else 0
    end_to_end_start = time.perf_counter()
    if not use_d3d11va:
        cpu_pipe_name = rf"\\.\pipe\telem_cpu_p010_{os.getpid()}"
        kernel32 = ctypes.windll.kernel32
        h_cpu_pipe = kernel32.CreateNamedPipeW(
            cpu_pipe_name,
            1, # PIPE_ACCESS_INBOUND
            0, # PIPE_TYPE_BYTE | PIPE_WAIT
            1, 0, 64 * 1024 * 1024, 1000, None
        )
        cmd_decode = [
            ffmpeg_exe, "-y",
            "-threads", "16",
            "-i", input_file_str,
            "-f", "rawvideo",
            "-pix_fmt", "p010le",
            "-y", cpu_pipe_name
        ]
        try:
            proc_dec = subprocess.Popen(
                cmd_decode,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
            kernel32.ConnectNamedPipe(h_cpu_pipe, None)
            p010_raw_arr = (ctypes.c_uint8 * frame_size)()
            p010_buf_addr = ctypes.addressof(p010_raw_arr)
            p010_c_buf = ctypes.cast(p010_buf_addr, POINTER(ctypes.c_uint8))
            print(f"[AMD NATIVE D3D11] FFmpeg P010 10-bit decoder pipe active: {cpu_pipe_name}", flush=True)
        except Exception as e:
            print(f"[AMD NATIVE D3D11] ERROR: Failed to launch decoder pipe: {e}", flush=True)
            _cleanup_native_resources()
            return False
    else:
        print("[AMD NATIVE D3D11VA] FFmpeg rawvideo decoder pipe: OFF (D3D11VA VCN active)", flush=True)

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
            project_elapsed_s=(
                video_timeline.frame_to_activity_elapsed(frame_idx, target_fps)
                if video_timeline is not None
                else frame_idx / target_fps
            ),
        )
    # ── MAP ETAP 1: Ensure 100% of required map tiles are cached before frame loop ──
    from src.indicators.moving_map import ensure_map_tiles_cached
    from src.moving_map import set_map_network_allowed, reset_map_tile_stats, get_map_tile_stats

    if layout.get("indicators", {}).get("track_map", {}).get("enabled", True):
        _map_t0 = time.perf_counter()
        preload_info = ensure_map_tiles_cached(
            video_width, video_height, layout, "track_map", gps_track,
            cancel_event=cancel_event,
        )
        print(
            f"[AMD Map Preload] provider={preload_info.get('provider')} "
            f"zoom={preload_info.get('zoom')} margin={preload_info.get('margin')} "
            f"required={preload_info.get('required')} "
            f"cached={preload_info.get('cached')} downloaded={preload_info.get('downloaded')} "
            f"missing_before_render={preload_info.get('missing')}",
            flush=True,
        )
        progress_tracker.hud_work(2, 8, "map preload/cache")
        print(f"[HUD] map preload duration={time.perf_counter() - _map_t0:.3f}s", flush=True)
    else:
        progress_tracker.hud_work(2, 8, "map disabled")

    reset_map_tile_stats()
    set_map_network_allowed(False)

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
            video_timeline=video_timeline,
            progress_cb=lambda done, total, label: progress_tracker.hud_work(
                (2.0 + 2.5 * done / max(1, total)) if label == "timeline"
                else (4.5 + 1.5 * done / max(1, total)) if label == "frame records"
                else 4.5,
                8,
                f"{label} {done}/{total}" if label in ("timeline", "frame records") else label,
            ),
        )
        print(
            f"[AMD NATIVE D3D11] AMD_TELEMETRY_MODE=PRECOMPUTED: "
            f"cache {telemetry_cache.frames} frames, build "
            f"{telemetry_cache.build_ms:.1f} ms, mem "
            f"{telemetry_cache.memory_bytes / (1024.0 * 1024.0):.3f} MiB",
            flush=True,
        )
    t_precompute_end = time.perf_counter()
    progress_tracker.hud_work(7, 8, "native HUD resources")

    # Main Frame Processing Loop
    # ── ETAP 8T-B/C: Unified Producer-Consumer Frame Pipeline ──
    pipeline_mode = os.getenv("AMD_CPU_GPU_PIPELINE", "ASYNC").upper()
    if pipeline_mode not in ("ASYNC", "SYNC"):
        pipeline_mode = "ASYNC"
    print(f"[AMD NATIVE D3D11] AMD_CPU_GPU_PIPELINE={pipeline_mode}", flush=True)

    previous_bboxes_holder = [{}] # Mutable cell for producer
    sparse_clusters_holder: list[Any] = [None]
    sparse_tiles_holder: list[dict[Any, Any]] = [{}]
    # ETAP 2A FIX: last gauge tile rect sent to the GPU as (x, y, w, h) or
    # None.  Producer-side cell mirroring the DLL's m_gaugePrev* bookkeeping;
    # used to force-reupload BELOW widgets intersecting the early-clear erase
    # region (current ∪ previously sent tile).
    previous_gauge_tile_holder: list[tuple[int, int, int, int] | None] = [None]

    # ── ETAP 2B/2C: producer-side state for the dynamic-region gauge transfer ──
    # geom tracks the current epoch key: (gw, gh, gx, gy) for MANUAL_RECTS;
    # extended with hash(style-signature) for ETAP 2C AUTO ("fallback" marks
    # unsupported frames sharing one full-tile epoch). The first frame of an
    # epoch — and every Nth frame after — performs a full-tile upload while
    # the rest use tight sub-box updates. auto_prev_* cache the PREVIOUS
    # frame's tile-local dynamic supports so moved elements get erased by the
    # next frame's crop bytes instead of ghosting over stale art.
    gauge_region_state: dict[str, Any] = {
        "geom": None, "frame_in_geom": 0,
        "epoch_changes": 0, "mode": "-",
        "auto_prev_needle": None,   # (x0,y0,x1,y1) tile-local or None
        "auto_prev_text": None,     # (x0,y0,x1,y1) tile-local or None
    }

    # ── ETAP 2C DIAGNOSTIC (env-gated oracle validator; zero cost when OFF) ──
    # AMD_GAUGE_REGION_ORACLE=1 diffs consecutive gauge tiles (numpy,
    # probe-only CPU cost) and asserts that every changed pixel lies inside a
    # rectangle actually sent to the consumer this frame. MISSED DYNAMIC
    # PIXELS must remain 0 for the whole run.
    _gauge_oracle_enabled = _env_flag("AMD_GAUGE_REGION_ORACLE", False)
    _gauge_oracle_state: dict[str, Any] = {
        "enabled": bool(_gauge_oracle_enabled),
        "frames": 0,
        "region_frames": 0,
        "full_frames": 0,
        "changed_pixels": 0,
        "covered_pixels": 0,
        "missed_dynamic_pixels": 0,
        "worst_frame_missed": 0,
        "violations": [],
        "prev_arr": None,
    }

    # ── ETAP 3H: Fine dynamic dirty state tracking ──
    above_fine_prev_dirty: dict[str, tuple[int, int, int, int]] = {}

    # ── ETAP 2B DIAGNOSTIC (temporary, env-gated) ──
    # Gauge tile variability measurement: when AMD_GAUGE_VARIABILITY_PROBE=1
    # the producer diffs consecutive gauge captures (numpy, probe-only CPU
    # cost) and records changed-pixel / tight-bbox / full-tile-hash statistics
    # so the 2B transfer design can be built on data instead of guessing.
    # Inert (zero cost) unless the env flag is set.
    _gauge_var_probe = _env_flag("AMD_GAUGE_VARIABILITY_PROBE", False)
    _gauge_var_state: dict[str, Any] = {
        "geom": None,       # (gw, gh) of last measured capture
        "prev": None,       # previous frame's HxWx4 uint8 array
        "union": None,      # accumulated bool mask of all changed pixels
        "frames": [],       # per-frame records
        "missing": 0,       # frames where no gauge capture happened
    }
    if _gauge_var_probe:
        print(
            "[AMD NATIVE D3D11] ETAP 2B DIAGNOSTIC: gauge variability probe "
            "ACTIVE (AMD_GAUGE_VARIABILITY_PROBE=1)",
            flush=True,
        )

    # ETAP 5K.1: AMD_ABOVE_BATCHED default 0 (OFF / legacy per-region default).
    # Opt-in experimental batched fast-path via AMD_ABOVE_BATCHED=1.
    above_batched_requested = os.getenv("AMD_ABOVE_BATCHED", "0").strip().lower() in ("1", "true", "yes", "on")
    above_batched_supported = hasattr(native_dll, "telem_amd_update_above_regions_batch")
    above_batched_enabled = above_batched_requested and above_batched_supported
    batched_above_rects_buf = (HUDDirtyRect * 8)() if above_batched_enabled else None
    if above_batched_enabled:
        print("[AMD NATIVE D3D11] AMD_ABOVE_BATCHED = 1 (batched native dirty regions fast-path active)", flush=True)
    else:
        print(f"[AMD NATIVE D3D11] AMD_ABOVE_BATCHED = 0 (legacy per-region upload mode, requested={above_batched_requested}, supported={above_batched_supported})", flush=True)

    map_geometry_set_holder = [False]
    last_hud_report_holder = [0.0]
    timeline_trace = [] # Required accounting checkpoints only
    audit_alloc_frames: list[dict[str, Any]] = []
    
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
        if overlay_profile_enabled:
            overlay_profiler.start_frame(idx, video_width, video_height)
        sample_time_sec = idx / target_fps
        # The native decoder consumes the compressed project-global axis, but
        # every telemetry/map/chart lookup must use the active clip's own
        # absolute timestamp.  Do not reintroduce ``base_dt + global`` here:
        # that would fill real recording gaps with fake telemetry time.
        c_dt = (
            video_timeline.frame_to_absolute(idx, target_fps)
            if video_timeline is not None
            and getattr(video_timeline, "clip_count", 0)
            else (base_dt + timedelta(seconds=sample_time_sec)
                  if base_dt is not None else None)
        )
        
        if audit_allocs_enabled:
            _aud_blocks0 = sys.getallocatedblocks()
            _aud_traced0 = tracemalloc.get_traced_memory()[0] if tracemalloc.is_tracing() else 0
        else:
            _aud_blocks0 = 0
            _aud_traced0 = 0

        t_samples_p: dict[str, float] = {}
        above_stats_p: dict[str, Any] = {}
        _producer_accounting_enabled = fa_enabled or _env_flag("AMD_PRODUCTION_ACCOUNTING", False) or bottleneck_proof_enabled
        _producer_accounting_last = t_p_start

        def _producer_stage(name: str) -> None:
            nonlocal _producer_accounting_last
            if not _producer_accounting_enabled:
                return
            _now = time.perf_counter()
            t_samples_p[f"producer_active.{name}"] = (_now - _producer_accounting_last) * 1000.0
            _producer_accounting_last = _now
        
        if not hud_work_enabled:
            t_p_end = time.perf_counter()
            if overlay_profile_enabled:
                overlay_profiler.finish_frame()
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
                map_heading=0.0,
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
        _producer_stage("telemetry_resolve")
        
        nonlocal gpu_chart_keys, gpu_chart_reason, gauge_gpu_active, gauge_gpu_reason
        nonlocal gpu_chart_keys_before_map, gpu_chart_keys_after_map, after_map_captures_performed
        nonlocal above_fine_prev_dirty
        if idx == 0 and gpu_charts_requested and not (gpu_chart_keys or gpu_chart_keys_after_map):
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
            _gpu_chart_keys_all, gpu_chart_reason = _chart_gpu_layout_safe(
                _probe_bboxes, _probe_capture, _probe_map_dst,
            )
            # ETAP 1A & 1B: Strict separation of BEFORE-MAP and AFTER-MAP chart keys.
            gpu_chart_keys_before_map = _gpu_chart_keys_all & before_map_chart_keys
            # For AFTER-MAP charts, they are composited via BlendAfterMapCharts after the map/dist_visual,
            # so they are validly eligible for native AFTER-MAP GPU_SPLIT.
            gpu_chart_keys_after_map = set(after_map_chart_keys)
            # Existing native BlendCharts pass runs BEFORE BlendAboveMap, so it
            # MUST only receive before-map charts to preserve Z-order.
            gpu_chart_keys = gpu_chart_keys_before_map

            print(
                f"[AMD NATIVE D3D11] Chart classification: "
                f"BEFORE_MAP={sorted(before_map_chart_keys)} (active GPU={sorted(gpu_chart_keys_before_map)}), "
                f"AFTER_MAP={sorted(after_map_chart_keys)} (diagnostic GPU-eligible={sorted(gpu_chart_keys_after_map)}) "
                f"({gpu_chart_reason})",
                flush=True,
            )
            if gpu_chart_keys:
                print(
                    f"[AMD NATIVE D3D11] GPU charts active (BEFORE_MAP): {sorted(gpu_chart_keys)} "
                    f"({gpu_chart_reason})",
                    flush=True,
                )
            elif (
                after_map_chart_gpu and gpu_charts_split
                and gpu_chart_keys_after_map and map_above_layout is not None
            ):
                # ETAP 2E: all active charts live AFTER the map -> they are
                # composited via the native AFTER-MAP GPU_SPLIT pass, so an
                # empty BEFORE-MAP set is expected and is NOT a fallback.
                # The old unconditional "GPU charts fallback" message here was
                # misleading (it logged the whole-layout probe reason while
                # AFTER-MAP capture ran normally).
                print(
                    f"[AMD NATIVE D3D11] GPU charts AFTER-MAP GPU_SPLIT ACTIVE: "
                    f"{sorted(gpu_chart_keys_after_map)} "
                    f"(CPU ABOVE HR: NO; CPU ABOVE CADENCE: NO)",
                    flush=True,
                )
            elif gpu_chart_keys_after_map or before_map_chart_keys:
                print(
                    f"[AMD NATIVE D3D11] GPU charts fallback -> CPU_REFERENCE "
                    f"({gpu_chart_reason})",
                    flush=True,
                )
            else:
                print(
                    "[AMD NATIVE D3D11] GPU charts: no active chart widgets in layout",
                    flush=True,
                )
            if gauge_gpu_requested:
                if after_map_gauge_gpu and map_above_layout is not None:
                    # ETAP 2A: gauge is in map_above_layout; probe happens during
                    # the above_full render on frame 0.  Safety check: disjoint
                    # from after-map chart bboxes only (map overlap is OK).
                    # We defer the actual safety check to the first above_full
                    # render (below), since _probe_bboxes comes from semantic_layout.
                    # Mark as tentatively active; confirmed in the above-map section.
                    gauge_gpu_active = True
                    gauge_gpu_reason = "AFTER-MAP probe deferred to above_full render"
                    print(
                        f"[AMD NATIVE D3D11] GPU gauge AFTER-MAP probe deferred "
                        f"(will confirm on first above_full render)",
                        flush=True,
                    )
                else:
                    # ETAP 5L legacy: gauge runs BEFORE map, must be disjoint from all.
                    _g_bbox = _probe_bboxes.get(gauge_layout_key)
                    gauge_gpu_active, gauge_gpu_reason = _gauge_gpu_layout_safe(
                        _g_bbox, _probe_bboxes, _probe_capture, _probe_map_dst,
                        gauge_key=gauge_layout_key,
                    )
                    print(
                        f"[AMD NATIVE D3D11] GPU gauge (BEFORE-MAP legacy) "
                        f"{'active' if gauge_gpu_active else 'fallback -> CPU_REFERENCE'} "
                        f"bbox={_g_bbox} ({gauge_gpu_reason})",
                        flush=True,
                    )

        _bboxes = {}
        gpu_capture: dict[str, dict[str, Any]] = {}
        capture_keys = set(gpu_chart_keys)
        if gauge_gpu_active:
            capture_keys.add(gauge_layout_key)
            
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
            _production_accounting_role="below",
            **frame_kwargs
        )
        compose_elapsed_ms = (time.perf_counter() - compose_start) * 1000.0
        t_samples_p["compose_overlay"] = compose_elapsed_ms
        _producer_stage("below_map_compose")

        # ETAP 2A DIAGNOSTIC (temporary, env-gated): dump compose ground truth
        # so HUD-canvas parity diffs can be attributed to source content vs
        # canvas state.  Value = run tag (e.g. ref / cand).  Dump frame list
        # follows AMD_HUD_DUMP_FRAMES (comma-separated) when set, else 30/300.
        _probe_tag = os.environ.get("AMD_ETAP2A_COMPOSE_PROBE")
        if _probe_tag:
            _raw_frames = os.environ.get("AMD_HUD_DUMP_FRAMES")
            _probe_frames = (
                {int(_t) for _t in _raw_frames.split(",") if _t.strip()}
                if _raw_frames else {30, 300}
            )
            if idx in _probe_frames:
                composed_img.save(
                    rf"scratch/etap2a_test/compose_full_{_probe_tag}_f{idx}.png")
                _band = composed_img.crop((1350, 1530, 2490, 1670))
                _ba = np.asarray(_band)
                _n170 = int(np.all(_ba == np.array([0, 0, 0, 170], dtype=np.uint8), axis=-1).sum())
                print(f"[ETAP2A PROBE] f{idx} compose band 170s={_n170}", flush=True)

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
        # ETAP 10R EXACT per-frame counters (mirrored into above_stats_p so the
        # consumer can sample them per frame).
        above_exact_clusters_frame = 0
        above_scan_fallback_clusters_frame = 0
        above_exact_fallback_reason_frame: dict[str, int] = {}
        
        # ETAP 2A: Initialize above_gpu_capture so gauge code below can always
        # reference it regardless of whether map_above_layout is active.
        above_gpu_capture: dict[str, dict[str, Any]] = {}
        above_bboxes: dict[str, tuple[int, int, int, int]] = {}

        if map_above_layout is not None:
            above_bboxes = {}
            above_tight_bboxes: dict[str, Any] | None = (
                {} if above_dirty_mode == "EXACT" else None
            )
            above_cache_enabled = os.getenv("AMD_ABOVE_TEXT_CACHE", "1") != "0"
            above_reuse = "above" if above_cache_enabled else False
            above_compose_start = time.perf_counter()
            reset_tight_bbox_collect()

            # ETAP 1B: When after_map_chart_gpu is active, capture after-map charts and omit them from above_full CPU render
            # ETAP 2A: When after_map_gauge_gpu is active, also capture gauge from above layout
            above_gpu_capture = {}  # reset for this frame (was pre-initialized above)
            above_capture_keys: set[str] = set(gpu_chart_keys_after_map if after_map_chart_gpu else set())
            # ETAP 2E: gate the gauge capture on the LAYOUT-RESOLVED gauge key,
            # not the v10 hard-code (user layouts use e.g. ``speed_text``).
            if after_map_gauge_gpu and gauge_gpu_active and gauge_layout_key in map_above_layout.get("indicators", {}):
                above_capture_keys.add(gauge_layout_key)
            above_split_keys = gpu_chart_keys_after_map if (after_map_chart_gpu and gpu_charts_split) else None

            if above_sparse_compose_enabled:
                # ── ETAP 4B: AMD_ABOVE_SPARSE_COMPOSE ─────────────────────────
                # Directly render disjoint widgets / clusters into local tiles,
                # bypassing 3840x2160 full canvas allocations and global crops.
                if above_capture_keys:
                    compose_overlay(
                        canvas_w=video_width,
                        canvas_h=video_height,
                        layout=map_above_layout,
                        font_path=font_path,
                        _bboxes={},
                        _tight_bboxes={},
                        render_keys=above_capture_keys,
                        gpu_capture_keys=above_capture_keys,
                        gpu_capture=above_gpu_capture,
                        split_chart_keys=above_split_keys,
                        target_image=None,
                        reuse_canvas=False,
                        **frame_kwargs,
                    )

                # Initialize cluster partition from frame 0 layout bboxes if needed
                if sparse_clusters_holder[0] is None:
                    _probe_bboxes = {}
                    compose_overlay(
                        canvas_w=video_width,
                        canvas_h=video_height,
                        layout=map_above_layout,
                        font_path=font_path,
                        _bboxes=_probe_bboxes,
                        gpu_capture_keys=above_capture_keys,
                        gpu_capture={},
                        split_chart_keys=above_split_keys,
                        reuse_canvas=False,
                        **frame_kwargs,
                    )
                    _cpu_boxes = {k: v for k, v in _probe_bboxes.items() if k not in above_capture_keys}
                    sparse_clusters_holder[0] = _cluster_above_bboxes_members(
                        _cpu_boxes, video_width, video_height, pad=16, merge_dist=32, max_regions=above_multi_rect_max
                    )
                    sparse_tiles_holder[0] = {
                        tuple(members): Image.new("RGBA", (cw, ch), (0, 0, 0, 0))
                        for (cx, cy, cw, ch), members in sparse_clusters_holder[0]
                    }

                clusters_with_members = sparse_clusters_holder[0]
                above_regions_out = []
                above_candidate_pixels = 0
                above_uploaded_pixels = 0
                above_uploaded_bytes = 0
                t_tobytes_total = 0.0

                for (cx, cy, cw, ch), members in clusters_with_members:
                    above_candidate_pixels += cw * ch
                    tile = sparse_tiles_holder[0][tuple(members)]
                    tile.paste((0, 0, 0, 0), (0, 0, cw, ch))
                    sub_tight = {}
                    compose_overlay(
                        canvas_w=video_width,
                        canvas_h=video_height,
                        layout=map_above_layout,
                        font_path=font_path,
                        _bboxes=above_bboxes,
                        _tight_bboxes=sub_tight,
                        render_keys=set(members),
                        target_image=tile,
                        coordinate_origin=(cx, cy),
                        reuse_canvas=False,
                        **frame_kwargs,
                    )
                    rects = []
                    unsafe = False
                    for m in members:
                        entry = sub_tight.get(m)
                        if entry is None or entry.get("clipped"):
                            unsafe = True
                            break
                        r = entry.get("rect")
                        if r is not None:
                            rects.append(tuple(int(v) for v in r))
                    if not unsafe and rects:
                        left = min(r[0] for r in rects)
                        top = min(r[1] for r in rects)
                        right = max(r[0] + r[2] for r in rects)
                        bottom = max(r[1] + r[3] for r in rects)
                        exact_rect = _clip_rect((left + cx, top + cy, right - left, bottom - top), video_width, video_height, pad=0)
                        if exact_rect is not None:
                            ex, ey, ew, eh = exact_rect
                            tight_crop = tile.crop((left, top, right, bottom))
                            t_tb_s = time.perf_counter()
                            r_bytes = tight_crop.tobytes("raw", "RGBA")
                            t_tobytes_total += (time.perf_counter() - t_tb_s) * 1000.0
                            above_regions_out.append((ex, ey, ew, eh, r_bytes))
                            above_uploaded_pixels += ew * eh
                            above_uploaded_bytes += len(r_bytes)
                    elif unsafe:
                        local_alpha_bbox = tile.getchannel("A").getbbox()
                        if local_alpha_bbox is not None:
                            lx, ly, rx, by = local_alpha_bbox
                            reg_w, reg_h = rx - lx, by - ly
                            reg_img = tile.crop(local_alpha_bbox)
                            t_tb_s = time.perf_counter()
                            r_bytes = reg_img.tobytes("raw", "RGBA")
                            t_tobytes_total += (time.perf_counter() - t_tb_s) * 1000.0
                            above_regions_out.append((cx + lx, cy + ly, reg_w, reg_h, r_bytes))
                            above_uploaded_pixels += reg_w * reg_h
                            above_uploaded_bytes += len(r_bytes)

                above_compose_ms = max(0.0, (time.perf_counter() - above_compose_start) * 1000.0 - t_tobytes_total)
                above_region_to_bytes_ms = t_tobytes_total
                above_stats_p = {
                    "region_count": len(above_regions_out),
                    "candidate_pixels": above_candidate_pixels,
                    "scanned_pixels": 0,
                    "uploaded_pixels": above_uploaded_pixels,
                    "uploaded_bytes": above_uploaded_bytes,
                    "candidate_crop_ms": 0.0,
                    "alpha_scan_ms": 0.0,
                    "final_crop_ms": 0.0,
                    "tobytes_ms": above_region_to_bytes_ms,
                    "tight_bbox_collect_ms": get_tight_bbox_collect_ms(),
                    "exact_union_ms": 0.0,
                    "exact_crop_ms": 0.0,
                    "exact_clusters": len(above_regions_out),
                    "scan_fallback_clusters": 0,
                    "exact_fallback_reason": {},
                }
            else:
                above_full = compose_overlay(
                    canvas_w=video_width,
                    canvas_h=video_height,
                    layout=map_above_layout,
                    font_path=font_path,
                    _bboxes=above_bboxes,
                    _tight_bboxes=above_tight_bboxes,
                    gpu_capture_keys=above_capture_keys,
                    gpu_capture=above_gpu_capture,
                    split_chart_keys=above_split_keys,
                    reuse_canvas=above_reuse,
                    _production_accounting_role="above",
                    **frame_kwargs,
                )
                above_compose_ms = (time.perf_counter() - above_compose_start) * 1000.0

            if os.environ.get("AMD_PRODUCTION_ACCOUNTING", "0").strip().lower() in {"1", "true", "yes", "on"}:
                record_production_accounting("above.compose_total", above_compose_ms)

            # ETAP 2A: On frame 0, resolve deferred AFTER-MAP gauge safety check.
            # The probe phase set gauge_gpu_active=True tentatively; now we have
            # above_bboxes from the actual map_above_layout render to confirm.
            if idx == 0 and after_map_gauge_gpu and gauge_gpu_active and \
               gauge_gpu_reason == "AFTER-MAP probe deferred to above_full render":
                # ETAP 2A: a captured key leaves compose_overlay's _bboxes
                # (compositor.py skips the CPU paste), so the gauge bbox lives
                # in above_gpu_capture[key]["bbox"] — fall back to above_bboxes
                # only if capture did not happen for any reason.
                _g_cap_above = above_gpu_capture.get(gauge_layout_key)
                if _g_cap_above is not None and "bbox" in _g_cap_above:
                    _g_bbox_above = _g_cap_above["bbox"]
                else:
                    _g_bbox_above = above_bboxes.get(gauge_layout_key)
                _after_chart_bboxes = {
                    k: above_bboxes[k]
                    for k in (gpu_chart_keys_after_map or set())
                    if k in above_bboxes
                }
                gauge_gpu_active, gauge_gpu_reason = _gauge_after_map_layout_safe(
                    _g_bbox_above, _after_chart_bboxes,
                )
                print(
                    f"[AMD NATIVE D3D11] GPU gauge AFTER-MAP "
                    f"{'active' if gauge_gpu_active else 'fallback -> CPU_REFERENCE'} "
                    f"key={gauge_layout_key} bbox={_g_bbox_above} ({gauge_gpu_reason})",
                    flush=True,
                )
                if not gauge_gpu_active:
                    # Fallback: gauge stays in CPU above_compose; remove from
                    # above_capture_keys so it renders on CPU from the next frame.
                    above_capture_keys.discard(gauge_layout_key)

            # ── ETAP 2E: one-shot GPU activation summary (frame 0) ─────────
            if idx == 0:
                _hr_on_gpu = (
                    after_map_chart_gpu and gpu_charts_split
                    and "fit_heart_rate_text" in gpu_chart_keys_after_map
                )
                _cad_on_gpu = (
                    after_map_chart_gpu and gpu_charts_split
                    and "fit_cadence_text" in gpu_chart_keys_after_map
                )
                print(
                    "[AMD NATIVE D3D11] GPU ACTIVATION SUMMARY: "
                    f"GPU MAP ACTIVE: {'YES' if gpu_map_enabled else 'NO'} | "
                    f"HR GPU ACTIVE: {'YES' if _hr_on_gpu else 'NO'} (CPU HR: {'NO' if _hr_on_gpu else 'YES'}) | "
                    f"CADENCE GPU ACTIVE: {'YES' if _cad_on_gpu else 'NO'} "
                    f"(CPU CADENCE: {'NO' if _cad_on_gpu else 'YES'}) | "
                    f"GAUGE GPU ACTIVE: {'YES' if gauge_gpu_active else 'NO'} "
                    f"(CPU GAUGE: {'NO' if gauge_gpu_active else 'YES'}, key={gauge_layout_key}) | "
                    f"GAUGE MODE: {gauge_region_mode}",
                    flush=True,
                )

            if not above_sparse_compose_enabled:
                plan_start = time.perf_counter()
                if above_multi_rect_enabled:
                    if above_fine_dirty_enabled and idx > 0:
                        above_region_plan_ms = 0.0
                        above_regions_out, above_stats_p, above_fine_prev_dirty = _extract_fine_dynamic_above_regions(
                            above_full, above_bboxes, above_tight_bboxes or {}, above_fine_prev_dirty,
                            video_width, video_height, max_regions=above_multi_rect_max,
                        )
                        above_exact_clusters_frame = above_stats_p.get("exact_clusters", 0)
                        above_scan_fallback_clusters_frame = 0
                        above_exact_fallback_reason_frame = {}
                        above_exact_counters["clusters"] += above_exact_clusters_frame
                    elif above_dirty_mode == "EXACT":
                        dirty_strat = os.environ.get("AMD_ABOVE_DIRTY_STRATEGY", "DIST").upper()
                        if dirty_strat == "AREA_COST":
                            clusters_with_members = _cluster_area_cost_members(
                                above_bboxes, video_width, video_height, pad=0, max_regions=above_multi_rect_max
                            )
                        elif dirty_strat == "DISCRETE":
                            clusters_with_members = [
                                ((box[0], box[1], box[2], box[3]), [k]) for k, box in above_bboxes.items()
                            ]
                        else:
                            # DIST (production default): cost-aware bounded distance merge (6 regions)
                            clusters_with_members = _cluster_above_bboxes_members(
                                above_bboxes, video_width, video_height, pad=16, merge_dist=32, max_regions=above_multi_rect_max
                            )
                        above_region_plan_ms = (time.perf_counter() - plan_start) * 1000.0
                        above_regions_out, above_stats_p = _extract_exact_above_regions(
                            above_full, clusters_with_members, above_tight_bboxes or {},
                            video_width, video_height,
                            batched_rects_buf=batched_above_rects_buf,
                        )
                        if idx == 0 and above_fine_dirty_enabled:
                            for _k, _box in above_bboxes.items():
                                _tight = (above_tight_bboxes or {}).get(_k)
                                above_fine_prev_dirty[_k] = _tight["bbox"] if (isinstance(_tight, dict) and "bbox" in _tight) else (_tight if isinstance(_tight, (tuple, list)) else _box)
                        above_exact_clusters_frame = above_stats_p.get("exact_clusters", 0)
                        above_scan_fallback_clusters_frame = above_stats_p.get("scan_fallback_clusters", 0)
                        above_exact_fallback_reason_frame = dict(above_stats_p.get("fallback_reason") or {})
                        above_exact_counters["clusters"] += above_exact_clusters_frame
                        above_exact_counters["fallback_clusters"] += above_scan_fallback_clusters_frame
                        for _reason, _cnt in above_exact_fallback_reason_frame.items():
                            above_exact_counters["fallback_reason"][_reason] = (
                                above_exact_counters["fallback_reason"].get(_reason, 0) + _cnt
                            )
                    else:
                        candidate_clusters = _cluster_above_bboxes(
                            above_bboxes, video_width, video_height, pad=16, merge_dist=32, max_regions=above_multi_rect_max
                        )
                        above_region_plan_ms = (time.perf_counter() - plan_start) * 1000.0
                        above_regions_out, above_stats_p = _extract_above_regions(
                            above_full, candidate_clusters, above_dirty_mode
                        )
                else:
                    # AMD ETAP 3E: Single Union mode (legacy reference ONE UNION RECT)
                    cand = _rendered_bbox_union(
                        above_bboxes, video_width, video_height, pad=64
                    )
                    candidate_clusters = [cand] if cand is not None else []
                    above_region_plan_ms = (time.perf_counter() - plan_start) * 1000.0
                    if above_dirty_mode == "EXACT" and candidate_clusters:
                        clusters_with_members = [(candidate_clusters[0], list(above_bboxes.keys()))]
                        above_regions_out, above_stats_p = _extract_exact_above_regions(
                            above_full, clusters_with_members, above_tight_bboxes or {},
                            video_width, video_height,
                        )
                    else:
                        above_regions_out, above_stats_p = _extract_above_regions(
                            above_full, candidate_clusters, above_dirty_mode
                        )
                above_candidate_crop_ms = above_stats_p["candidate_crop_ms"]
                above_local_alpha_scan_ms = above_stats_p["alpha_scan_ms"]
                above_final_crop_ms = above_stats_p["final_crop_ms"]
                above_region_to_bytes_ms = above_stats_p["tobytes_ms"]
                above_candidate_pixels = above_stats_p["candidate_pixels"]
                above_scanned_pixels = above_stats_p["scanned_pixels"]
                above_uploaded_pixels = above_stats_p["uploaded_pixels"]
                above_uploaded_bytes = above_stats_p["uploaded_bytes"]
                t_samples_p["above_tight_bbox_collect"] = above_stats_p.get("tight_bbox_collect_ms", 0.0)
                t_samples_p["above_exact_union"] = above_stats_p.get("exact_union_ms", 0.0)
                t_samples_p["above_exact_crop"] = above_stats_p.get("exact_crop_ms", 0.0)

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
            "exact_clusters": above_exact_clusters_frame,
            "scan_fallback_clusters": above_scan_fallback_clusters_frame,
            "exact_fallback_reason": dict(above_exact_fallback_reason_frame),
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

        # ETAP 1A & 1B: AFTER-MAP chart capture
        after_map_chart_captures_frame: list[AfterMapChartTile] = []
        if (after_map_chart_capture_diag or after_map_chart_gpu) and gpu_chart_keys_after_map and map_above_layout is not None:
            if after_map_chart_gpu and above_gpu_capture:
                _diag_after_capture = above_gpu_capture
            else:
                after_map_capture_layout = {
                    "indicators": {k: copy.deepcopy(map_above_layout["indicators"][k]) for k in after_map_chart_keys if k in map_above_layout.get("indicators", {})},
                    "custom_texts": [],
                }
                _diag_after_capture = {}
                compose_overlay(
                    canvas_w=video_width,
                    canvas_h=video_height,
                    layout=after_map_capture_layout,
                    font_path=font_path,
                    gpu_capture_keys=after_map_chart_keys,
                    gpu_capture=_diag_after_capture,
                    split_chart_keys=(after_map_chart_keys if gpu_charts_split else None),
                    reuse_canvas=False,
                    fast_preview=False,
                    **frame_kwargs,
                )
            for _ack in after_map_chart_keys:
                _cap = _diag_after_capture.get(_ack)
                if _cap is None:
                    continue
                _abx, _aby, _abw, _abh = _cap["bbox"]
                _aslot = _CHART_GPU_SLOTS.get(_ack, 0)
                _center = _cap.get("center", (_abx + _abw // 2, _aby + _abh // 2))
                _rot = _cap.get("rotation", 0)

                _st_bytes = None
                _st_w, _st_h, _st_stride = 0, 0, 0
                _c_bytes, _cw, _ch, _c_stride = None, 0, 0, 0
                _c_local = (0, 0)
                _v_bytes, _vw, _vh, _v_stride = None, 0, 0, 0
                _v_local = (0, 0)

                if gpu_charts_split and _cap.get("split"):
                    _static_img = _cap["static"]
                    _st_w, _st_h = _static_img.width, _static_img.height
                    _st_stride = _st_w * 4
                    if _ack not in after_map_chart_static_uploaded:
                        after_map_chart_static_uploaded.add(_ack)
                        _st_bytes = _static_img.tobytes("raw", "RGBA")

                    _ct = _cap.get("cursor_tile")
                    if _ct is not None:
                        _c_local = _cap.get("cursor_local", (0, 0))
                        _cw, _ch = _ct.width, _ct.height
                        _c_stride = _cw * 4
                        _c_bytes = _ct.tobytes("raw", "RGBA")

                    _vt = _cap.get("value_tile")
                    if _vt is not None:
                        _v_local = _cap.get("value_local", (0, 0))
                        _vw, _vh = _vt.width, _vt.height
                        _v_stride = _vw * 4
                        _v_bytes = _vt.tobytes("raw", "RGBA")
                else:
                    _chart_img = _cap.get("image")
                    if _chart_img is not None:
                        _st_w, _st_h = _chart_img.width, _chart_img.height
                        _st_stride = _st_w * 4
                        _st_bytes = _chart_img.tobytes("raw", "RGBA")

                _tile = AfterMapChartTile(
                    chart_key=_ack,
                    slot=_aslot,
                    placement="AFTER_MAP",
                    bbox=(_abx, _aby, _abw, _abh),
                    center=_center,
                    rotation=_rot,
                    static_bytes=_st_bytes,
                    static_width=_st_w,
                    static_height=_st_h,
                    static_stride=_st_stride,
                    cursor_bytes=_c_bytes,
                    cursor_width=_cw,
                    cursor_height=_ch,
                    cursor_stride=_c_stride,
                    cursor_local=_c_local,
                    value_bytes=_v_bytes,
                    value_width=_vw,
                    value_height=_vh,
                    value_stride=_v_stride,
                    value_local=_v_local,
                    format="DXGI_FORMAT_R8G8B8A8_UNORM",
                    is_valid=True,
                )
                after_map_chart_captures_frame.append(_tile)
                after_map_captures_performed += 1

        # Gauge
        gauge_data = None
        gauge_region_data: list[tuple[bytes, int, int, int, int]] | None = None
        gauge_tile_bbox: tuple[int, int, int, int] | None = None
        gauge_capture_ms = 0.0
        gauge_diff_ms = 0.0
        gauge_bytes_frame = 0
        gauge_tobytes_ms = 0.0
        # ETAP 2C AUTO: set when the persistent GPU texture needs NO byte
        # updates this frame but start-of-frame HUD clears must still run
        # (the map moves underneath the erased gauge tile bbox).
        gauge_clear_only_frame = False
        if gauge_gpu_active:
            # ETAP 2A: gauge is captured from map_above_layout (above_gpu_capture).
            # above_gpu_capture is only populated when map_above_layout is not None.
            _gauge_source = above_gpu_capture if (after_map_gauge_gpu and map_above_layout is not None) else gpu_capture
            gauge_cap = _gauge_source.get(gauge_layout_key)
            if gauge_cap is not None and "image" in gauge_cap:
                gauge_img = gauge_cap["image"]
                gx, gy, gw, gh = gauge_cap["bbox"]
                # ETAP 2C: raw UNCLIPPED widget origin on the canvas. Region
                # derivation maps renderer-reported widget-local supports
                # into tile coordinates via (cx0 - _wgx, cy0 - _wgy).
                _wgx, _wgy = int(gx), int(gy)
                cx0, cy0 = max(0, gx), max(0, gy)
                cx1, cy1 = min(video_width, gx + gw), min(video_height, gy + gh)
                if cx1 > cx0 and cy1 > cy0:
                    # ETAP 2B: only clip-copy the widget image when it actually
                    # leaves the canvas; a full-size crop is a needless tile
                    # memcpy in the common fully-on-canvas case.
                    if (cx0 != gx or cy0 != gy
                            or cx1 - cx0 != gw or cy1 - cy0 != gh):
                        _cap_start = time.perf_counter()
                        gauge_img = gauge_img.crop(
                            (cx0 - gx, cy0 - gy, cx1 - gx, cy1 - gy))
                        gauge_capture_ms = (
                            time.perf_counter() - _cap_start) * 1000.0
                        gw, gh = cx1 - cx0, cy1 - cy0
                    gx, gy = cx0, cy0
                    gw, gh = cx1 - cx0, cy1 - cy0
                    gauge_tile_bbox = (gx, gy, gw, gh)

                    # ── ETAP 2B/2C: dynamic-region transfer ──────────────
                    # MANUAL_RECTS (ETAP 2B): configured sub-rectangles.
                    # AUTO (ETAP 2C): rectangles derived from renderer-
                    # reported dynamic supports; any style/geometry signature
                    # change resets the epoch and forces a full-tile upload;
                    # unsupported configs fall back to FULL_TILE — never CPU.
                    _do_region = bool(
                        after_map_gauge_gpu
                        and gauge_region_mode in ("MANUAL_RECTS", "AUTO"))
                    _auto_info = None
                    _auto_ok = False
                    if _do_region and gauge_region_mode == "AUTO":
                        _auto_info = get_gauge_dynamic_info(gauge_layout_key)
                        _auto_ok = bool(
                            isinstance(_auto_info, dict)
                            and _auto_info.get("supported")
                            and int(_auto_info.get("rotation", 0)) % 360 == 0)
                    if _do_region:
                        if gauge_region_mode == "MANUAL_RECTS":
                            _epoch: Any = (gw, gh, gx, gy)
                        elif _auto_ok:
                            _epoch = (gw, gh, gx, gy,
                                      hash(_auto_info["sig"]))
                        else:
                            # shared fallback epoch: consecutive unsupported
                            # frames do NOT re-trigger epoch logs/uploads
                            _epoch = (gw, gh, gx, gy, "fallback")
                        if gauge_region_state["geom"] != _epoch:
                            gauge_region_state["geom"] = _epoch
                            gauge_region_state["frame_in_geom"] = 0
                            gauge_region_state["auto_prev_needle"] = None
                            gauge_region_state["auto_prev_text"] = None
                            gauge_region_state["epoch_changes"] += 1
                            _mode_label = (
                                "MANUAL_RECTS"
                                if gauge_region_mode == "MANUAL_RECTS"
                                else ("AUTO_SAFE" if _auto_ok
                                      else "AUTO_FALLBACK_FULLTILE"))
                            gauge_region_state["mode"] = _mode_label
                            print(
                                f"[AMD GAUGE GPU] mode={_mode_label} rects="
                                + (str(len(gauge_dynamic_rects))
                                   if gauge_region_mode == "MANUAL_RECTS"
                                   else "-")
                                + f" geometry={gw}x{gh}"
                                + f" full_refresh={gauge_full_refresh_n}",
                                flush=True)
                        _fig = gauge_region_state["frame_in_geom"]
                        _do_region = bool(
                            _fig > 0
                            and (gauge_region_mode == "MANUAL_RECTS" or _auto_ok)
                            and (_fig % max(1, gauge_full_refresh_n)) != 0)
                    # ETAP 2C: refresh the cached supports EVERY frame (also
                    # on full/resync frames) so the previous-capture supports
                    # used for erase coverage are never staler than one frame
                    # — otherwise the first region frame after a full-tile
                    # resync could leave stale needle art between positions.
                    _prev_needle = None
                    _prev_text = None
                    if gauge_region_mode == "AUTO" and _auto_ok:
                        _prev_needle = gauge_region_state["auto_prev_needle"]
                        _prev_text = gauge_region_state["auto_prev_text"]
                        gauge_region_state["auto_prev_needle"] = (
                            _support_to_tile_rect(
                                _auto_info.get("needle_bbox"),
                                cx0 - _wgx, cy0 - _wgy, gw, gh))
                        gauge_region_state["auto_prev_text"] = (
                            _support_to_tile_rect(
                                _auto_info.get("text_bbox"),
                                cx0 - _wgx, cy0 - _wgy, gw, gh))
                    _oracle_rects: list[tuple[int, int, int, int]] = []
                    gauge_clear_only_frame = False
                    gauge_row_table_ptr = None
                    gauge_stride = gw * 4
                    if hasattr(gauge_img, "im") and hasattr(gauge_img.im, "ptr"):
                        try:
                            cap_name = ctypes.pythonapi.PyCapsule_GetName(gauge_img.im.ptr)
                            raw_ptr = ctypes.pythonapi.PyCapsule_GetPointer(gauge_img.im.ptr, cap_name)
                            if raw_ptr:
                                gauge_row_table_ptr = ctypes.c_void_p.from_address(raw_ptr + 40).value
                        except Exception:
                            gauge_row_table_ptr = None

                    if _do_region:
                        tb_start = time.perf_counter()
                        _regions: list[Any] = []
                        if gauge_region_mode == "MANUAL_RECTS":
                            for (_rx, _ry, _rw, _rh) in gauge_dynamic_rects:
                                _bx0 = max(0, min(int(_rx), gw))
                                _by0 = max(0, min(int(_ry), gh))
                                _bx1 = max(0, min(int(_rx) + int(_rw), gw))
                                _by1 = max(0, min(int(_ry) + int(_rh), gh))
                                if _bx1 <= _bx0 or _by1 <= _by0:
                                    continue
                                _oracle_rects.append((_bx0, _by0, _bx1, _by1))
                                _rw_box = _bx1 - _bx0
                                _rh_box = _by1 - _by0
                                is_contig = False
                                if gauge_row_table_ptr is not None:
                                    top_row = ctypes.c_void_p.from_address(gauge_row_table_ptr + _by0 * 8).value
                                    bottom_row = ctypes.c_void_p.from_address(gauge_row_table_ptr + (_by1 - 1) * 8).value
                                    if top_row and bottom_row and bottom_row == top_row + (_rh_box - 1) * gauge_stride:
                                        is_contig = True
                                        reg_ptr = top_row + _bx0 * 4
                                        _regions.append((None, _bx0, _by0, _rw_box, _rh_box, reg_ptr, gauge_stride, gauge_img))
                                if not is_contig:
                                    _sub = gauge_img.crop((_bx0, _by0, _bx1, _by1))
                                    _regions.append((
                                        _sub.tobytes("raw", "RGBA"),
                                        _bx0, _by0, _rw_box, _rh_box))
                        else:
                            # ETAP 2C AUTO derivation (tile-local): needle
                            # sweep band ∪ value-text box of THIS frame
                            # unioned with the PREVIOUS frame's supports so
                            # moved elements are erased by fresh bytes.
                            _auto_cur_rects: list[tuple[int, int, int, int]] = []
                            _u = _union_tile_rects(
                                _support_to_tile_rect(
                                    _auto_info.get("needle_bbox"),
                                    cx0 - _wgx, cy0 - _wgy, gw, gh),
                                _prev_needle)
                            if _u is not None:
                                _auto_cur_rects.append(_u)
                            _u = _union_tile_rects(
                                _support_to_tile_rect(
                                    _auto_info.get("text_bbox"),
                                    cx0 - _wgx, cy0 - _wgy, gw, gh),
                                _prev_text)
                            if _u is not None:
                                _auto_cur_rects.append(_u)
                            for (_bx0, _by0, _bx1, _by1) in _merge_tile_rects(
                                    _auto_cur_rects):
                                _oracle_rects.append((_bx0, _by0, _bx1, _by1))
                                _rw_box = _bx1 - _bx0
                                _rh_box = _by1 - _by0
                                is_contig = False
                                if gauge_row_table_ptr is not None:
                                    top_row = ctypes.c_void_p.from_address(gauge_row_table_ptr + _by0 * 8).value
                                    bottom_row = ctypes.c_void_p.from_address(gauge_row_table_ptr + (_by1 - 1) * 8).value
                                    if top_row and bottom_row and bottom_row == top_row + (_rh_box - 1) * gauge_stride:
                                        is_contig = True
                                        reg_ptr = top_row + _bx0 * 4
                                        _regions.append((None, _bx0, _by0, _rw_box, _rh_box, reg_ptr, gauge_stride, gauge_img))
                                if not is_contig:
                                    _sub = gauge_img.crop((_bx0, _by0, _bx1, _by1))
                                    _regions.append((
                                        _sub.tobytes("raw", "RGBA"),
                                        _bx0, _by0, _rw_box, _rh_box))
                        gauge_tobytes_ms = (
                            time.perf_counter() - tb_start) * 1000.0
                        if _regions:
                            gauge_region_data = _regions
                            gauge_bytes_frame = sum(
                                len(_r[0]) if _r[0] is not None else (_r[3] * _r[4] * 4)
                                for _r in _regions)
                        elif gauge_gpu_active:
                            # ETAP 2C AUTO: zero dynamic supports this frame —
                            # no bytes to upload, but start-of-frame HUD
                            # clears must still run (map moves underneath).
                            gauge_clear_only_frame = True
                    if not _do_region:
                        tb_start = time.perf_counter()
                        is_contig = False
                        if gauge_row_table_ptr is not None:
                            top_row = ctypes.c_void_p.from_address(gauge_row_table_ptr).value
                            bottom_row = ctypes.c_void_p.from_address(gauge_row_table_ptr + (gh - 1) * 8).value
                            if top_row and bottom_row and bottom_row == top_row + (gh - 1) * gauge_stride:
                                is_contig = True
                                gauge_data = (None, gauge_img.width, gauge_img.height, gx, gy, top_row, gauge_stride, gauge_img)
                                gauge_bytes_frame = gw * gh * 4
                        if not is_contig:
                            gauge_bytes = gauge_img.tobytes("raw", "RGBA")
                            gauge_bytes_frame = len(gauge_bytes)
                            gauge_data = (
                                gauge_bytes, gauge_img.width, gauge_img.height,
                                gx, gy)
                        gauge_tobytes_ms = (
                            time.perf_counter() - tb_start) * 1000.0
                    gauge_region_state["frame_in_geom"] += 1

                    # ── ETAP 2C DIAGNOSTIC (env-gated oracle validator) ───
                    # Diffs consecutive gauge tiles (numpy, probe-only cost;
                    # skipped entirely when AMD_GAUGE_REGION_ORACLE unset) and
                    # asserts every changed pixel lies inside a rectangle sent
                    # to the consumer this frame. MISSED must stay 0.
                    if _gauge_oracle_enabled:
                        _o_arr = np.asarray(gauge_img)
                        if (_gauge_oracle_state["prev_arr"] is not None
                                and _gauge_oracle_state["prev_arr"].shape
                                == _o_arr.shape):
                            _diff_mask = np.any(
                                _o_arr != _gauge_oracle_state["prev_arr"],
                                axis=2)
                            _chg = int(np.count_nonzero(_diff_mask))
                            _gauge_oracle_state["frames"] += 1
                            _gauge_oracle_state["changed_pixels"] += _chg
                            if _oracle_rects:
                                _cov = np.zeros(_diff_mask.shape, dtype=bool)
                                for (_ox0, _oy0, _ox1, _oy1) in _oracle_rects:
                                    _cov[_oy0:_oy1, _ox0:_ox1] = True
                                _missed = int(np.count_nonzero(
                                    _diff_mask & ~_cov))
                                _gauge_oracle_state["region_frames"] += 1
                                _gauge_oracle_state["covered_pixels"] += (
                                    _chg - _missed)
                                _gauge_oracle_state[
                                    "missed_dynamic_pixels"] += _missed
                                if _missed > _gauge_oracle_state[
                                        "worst_frame_missed"]:
                                    _gauge_oracle_state[
                                        "worst_frame_missed"] = _missed
                                if _missed and len(
                                        _gauge_oracle_state["violations"]) < 16:
                                    _gauge_oracle_state["violations"].append({
                                        "frame": int(idx),
                                        "missed": _missed})
                            else:
                                _gauge_oracle_state["full_frames"] += 1
                        elif _gauge_oracle_state["prev_arr"] is not None:
                            # Tile shape changed => geometry epoch switch:
                            # the producer forced a full-tile upload, so the
                            # whole surface is refreshed by definition.
                            _gauge_oracle_state["full_frames"] += 1
                        _gauge_oracle_state["prev_arr"] = _o_arr

                    # ETAP 2B DIAGNOSTIC (temporary, env-gated): consecutive
                    # capture diff for variability statistics.  Probe-only
                    # numpy cost; skipped entirely when flag unset.
                    if _gauge_var_probe:
                        import hashlib
                        _var_t0 = time.perf_counter()
                        _var_arr = np.asarray(gauge_img)
                        _var_asarray_ms = (time.perf_counter() - _var_t0) * 1000.0
                        _rec: dict[str, Any] = {
                            "frame": int(idx),
                            "x": int(gx), "y": int(gy),
                            "w": int(gw), "h": int(gh),
                            "md5": hashlib.md5(gauge_bytes).hexdigest(),
                            "asarray_ms": round(_var_asarray_ms, 4),
                        }
                        _geom_key = (int(gw), int(gh))
                        if _gauge_var_state["geom"] != _geom_key:
                            _gauge_var_state["geom"] = _geom_key
                            _gauge_var_state["union"] = np.zeros(
                                (int(gh), int(gw)), dtype=bool)
                            _gauge_var_state["prev"] = None
                            _rec["geometry_reset"] = True
                        _prev_arr = _gauge_var_state["prev"]
                        if _prev_arr is not None:
                            _ne = (
                                _prev_arr.view(np.uint32).reshape(int(gh), int(gw))
                                != _var_arr.view(np.uint32).reshape(int(gh), int(gw))
                            )
                            _n = int(np.count_nonzero(_ne))
                            _rec["changed_px"] = _n
                            if _n:
                                _ys, _xs = np.nonzero(_ne)
                                _bx0, _by0 = int(_xs.min()), int(_ys.min())
                                _bx1, _by1 = int(_xs.max()), int(_ys.max())
                                _rec["bbox_local"] = [
                                    _bx0, _by0, _bx1 - _bx0 + 1, _by1 - _by0 + 1]
                                _rec["bbox_bytes"] = int(
                                    (_bx1 - _bx0 + 1) * (_by1 - _by0 + 1) * 4)
                                _gauge_var_state["union"] |= _ne
                            else:
                                _rec["bbox_local"] = None
                                _rec["bbox_bytes"] = 0
                        _gauge_var_state["prev"] = _var_arr
                        _gauge_var_state["frames"].append(_rec)

                    # ETAP 2A DIAGNOSTIC (temporary, env-gated): save the gauge

                    # capture so validation can build the expected composited
                    # canvas (truth + gauge) for ghosting / tile-parity checks.
                    if os.environ.get("AMD_ETAP2A_COMPOSE_PROBE"):
                        _raw_frames = os.environ.get("AMD_HUD_DUMP_FRAMES")
                        _probe_frames = (
                            {int(_t) for _t in _raw_frames.split(",") if _t.strip()}
                            if _raw_frames else {30, 300}
                        )
                        if idx in _probe_frames:
                            gauge_img.save(
                                rf"scratch/etap2a_test/gauge_capture_f{idx}.png")
                            with open(rf"scratch/etap2a_test/gauge_meta_f{idx}.json",
                                      "w", encoding="utf-8") as _gf:
                                _gf.write(json.dumps({"x": int(gx), "y": int(gy),
                                                      "w": int(gw), "h": int(gh)}))
        t_samples_p["gauge_tobytes"] = gauge_tobytes_ms
        # ETAP 2B: capture = clip-crop cost (0 in steady state); diff = 0 by
        # design in fixed-region mode (dirty regions are pre-measured).
        t_samples_p["gauge_capture"] = gauge_capture_ms
        t_samples_p["gauge_diff"] = gauge_diff_ms
        t_samples_p["gauge_bytes_per_frame"] = float(gauge_bytes_frame)

        # Map
        _producer_stage("above_map_compose_and_capture")
        map_data = None
        map_geometry = None
        last_map_img_out = None
        last_map_dst_out = None
        map_timing_ms = 0.0
        map_heading_val = 0.0
        if gpu_map_enabled:
            map_start = time.perf_counter()
            if gpu_map_rotate:
                map_img, map_heading_val, map_dst, working_size = render_map_unrotated_working_image(
                    video_width, video_height, layout, "track_map",
                    gps_track, target_dt=c_dt, current_position=frame_kwargs.get("current_position"),
                    map_heading=frame_kwargs.get("map_heading"),
                )
            else:
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
                
                # Check for direct strided pointer
                map_row_table_ptr = None
                mw, mh = map_img.size
                map_stride = mw * 4
                if hasattr(map_img, "im") and hasattr(map_img.im, "ptr"):
                    try:
                        cap_name = ctypes.pythonapi.PyCapsule_GetName(map_img.im.ptr)
                        raw_ptr = ctypes.pythonapi.PyCapsule_GetPointer(map_img.im.ptr, cap_name)
                        if raw_ptr:
                            map_row_table_ptr = ctypes.c_void_p.from_address(raw_ptr + 40).value
                    except Exception:
                        map_row_table_ptr = None
                
                is_contig = False
                if map_row_table_ptr is not None:
                    top_row = ctypes.c_void_p.from_address(map_row_table_ptr).value
                    bottom_row = ctypes.c_void_p.from_address(map_row_table_ptr + (mh - 1) * 8).value
                    if top_row and bottom_row and bottom_row == top_row + (mh - 1) * map_stride:
                        is_contig = True
                        map_data = (None, mw, mh, map_dst, top_row, map_stride, map_img)
                if not is_contig:
                    map_bytes = map_img.tobytes("raw", "RGBA")
                    map_data = (map_bytes, mw, mh, map_dst, None, map_stride, map_img)
            map_timing_ms = (time.perf_counter() - map_start) * 1000.0
        t_samples_p["map_cpu_upload"] = map_timing_ms
        _producer_stage("map_cpu_preparation")

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
                if after_map_chart_gpu and "dist_visual" in _bboxes:
                    dv_rect = _bboxes["dist_visual"]
                    if dv_rect not in dirty_rects:
                        dirty_rects.append(dv_rect)
                # ETAP 2A FIX: the AFTER-MAP GPU gauge erases the previous
                # frame's FULL gauge tile bbox on the persistent HUD canvas
                # (telem_amd_run_early_clears -> ClearPreviousAboveMap) BEFORE
                # these dirty rects are uploaded.  Every BELOW widget whose
                # bbox intersects the erase region (current ∪ previously sent
                # gauge tile) must therefore be re-uploaded EVERY frame, or its
                # pixels are wiped and never restored (observed: missing
                # dist_visual ruler track under the gauge tile).
                if after_map_gauge_gpu:
                    _tiles: list[tuple[int, int, int, int]] = []
                    if previous_gauge_tile_holder[0] is not None:
                        _tiles.append(previous_gauge_tile_holder[0])
                    # ETAP 2B: use the gauge tile bbox (valid for BOTH the
                    # full-tile and the dynamic-region transfer paths) so
                    # BELOW widgets under the erase region keep being
                    # force-reuploaded every frame.
                    if gauge_tile_bbox is not None:
                        _tiles.append(gauge_tile_bbox)
                    if _tiles:
                        ex0 = min(t[0] for t in _tiles)
                        ey0 = min(t[1] for t in _tiles)
                        ex1 = max(t[0] + t[2] for t in _tiles)
                        ey1 = max(t[1] + t[3] for t in _tiles)
                        for wx, wy, ww, wh in _bboxes.values():
                            if wx < ex1 and wy < ey1 and ex0 < wx + ww and ey0 < wy + wh:
                                wr = (wx, wy, ww, wh)
                                if wr not in dirty_rects:
                                    dirty_rects.append(wr)
                    if gauge_tile_bbox is not None:
                        previous_gauge_tile_holder[0] = gauge_tile_bbox
                t_samples_p["HUD dirty bbox"] = (time.perf_counter() - bbox_start) * 1000.0
                dirty_rect_slices = []
                for rx, ry, rw, rh in dirty_rects:
                    slice_img = composed_img.crop((rx, ry, rx + rw, ry + rh))
                    slice_bytes = slice_img.tobytes("raw", "RGBA")
                    dirty_rect_slices.append((rx, ry, rw, rh, slice_bytes))
                    upload_bytes += rw * rh * 4
                intermediate_bytes = upload_bytes
                persistent_copy_bytes = upload_bytes
                rect_count = len(dirty_rects)
            t_samples_p["PIL/buffer preparation"] = (time.perf_counter() - buffer_prep_start) * 1000.0
            previous_bboxes_holder[0] = dict(_bboxes)

        if audit_allocs_enabled:
            t_samples_p["producer_alloc_blocks"] = float(sys.getallocatedblocks() - _aud_blocks0)
            t_samples_p["producer_alloc_traced_bytes"] = float(
                (tracemalloc.get_traced_memory()[0] - _aud_traced0) if tracemalloc.is_tracing() else 0.0
            )

        _producer_stage("dirty_region_and_buffer_preparation")
        _producer_stage("PreparedFrame_construction_boundary")
        t_p_end = time.perf_counter()
        prep_ms = (t_p_end - t_p_start) * 1000.0

        lean_transform_info = None
        _linfo = None
        if lean_gpu_enabled:
            _lval = None
            if "indicator_values" in frame_kwargs and lean_key in frame_kwargs["indicator_values"]:
                _lval = frame_kwargs["indicator_values"][lean_key]
            elif "indicator_values" in frame_kwargs and "lean_indicator" in frame_kwargs["indicator_values"]:
                _lval = frame_kwargs["indicator_values"]["lean_indicator"]
            elif "lean_indicator" in frame_kwargs.get("extra_indicators", {}):
                _lval = frame_kwargs["extra_indicators"]["lean_indicator"][0]
            _min_dim = min(video_width, video_height)
            _outline_raw = int(semantic_layout.get("global", {}).get("text_outline", 3))
            _outline = max(0, int(round(_outline_raw * _min_dim / 1000)))
            _fs_val = lean_cfg.get("font_size") if "font_size" in lean_cfg else lean_cfg.get("size", 0.02)
            _fs = max(8, s(_fs_val, _min_dim))
            _size_px = s(lean_cfg.get("size", 0.1), video_width)
            _thickness = 4
            _linfo = get_lean_gpu_transform_info(
                canvas_w=video_width,
                canvas_h=video_height,
                layout=semantic_layout,
                key=lean_key,
                value=_lval,
                cfg=lean_cfg,
                font_path=font_path,
                label=lean_cfg.get("label", ""),
                min_dim=_min_dim,
                fs=_fs,
                outline=_outline,
                thickness=_thickness,
                size_px=_size_px,
                ss=1,
            )
            if _linfo is not None:
                _ang, _grp, _px, _py, _spx, _spy, _dx, _dy, _tw, _th = _linfo
                lean_transform_info = (_ang, _px, _py, _spx, _spy, _dx, _dy, _tw, _th)

        if idx == 0:
            print(
                f"\nAMD_MAP_PARITY:\n"
                f"  enabled={1 if gpu_map_enabled else 0}\n"
                f"  dispatched=1\n"
                f"  rendered={1 if (gpu_map_enabled and last_map_img_out is not None) else 0}\n"
                f"  uploaded=1\n"
                f"  composed=1\n"
                f"  z_order=GPU_MAP (before CPU_ABOVE)\n"
                f"  rect={last_map_dst_out}",
                flush=True,
            )
            print(
                f"AMD_LEAN_PARITY:\n"
                f"  indicator_present={1 if lean_in_layout else 0}\n"
                f"  icon_present={1 if (lean_gpu_enabled or not lean_in_layout) else 0}\n"
                f"  source={lean_cfg.get('source', 'gyro') if lean_in_layout else 'none'}\n"
                f"  renderer={'GPU_LEAN_AFFINE' if lean_gpu_enabled else 'CPU_REFERENCE'}\n"
                f"  dynamic_rotation={1 if lean_gpu_enabled else 0}\n"
                f"  rect={(_linfo[6], _linfo[7], _linfo[8], _linfo[9]) if _linfo else None}\n"
                f"  composed=1\n",
                flush=True,
            )

        if overlay_profile_enabled:
            overlay_profiler.finish_frame()
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
            gauge_region_data=gauge_region_data,
            gauge_tile_bbox=gauge_tile_bbox,
            gauge_clear_only=gauge_clear_only_frame,
            above_regions=above_regions_out,
            map_active=gpu_map_enabled,
            map_data=map_data,
            map_geometry=map_geometry,
            map_heading=map_heading_val,
            timing_samples_producer=t_samples_p,
            intermediate_bytes=intermediate_bytes,
            persistent_copy_bytes=persistent_copy_bytes,
            upload_bytes=upload_bytes,
            rect_count=rect_count,
            above_stats=above_stats_p,
            last_map_img=last_map_img_out,
            last_map_dst=last_map_dst_out,
            map_crop_key=getattr(last_map_img_out, "_crop_key", None),
            after_map_chart_captures=after_map_chart_captures_frame,
            lean_active=lean_gpu_enabled,
            lean_transform=lean_transform_info,
        )

    last_uploaded_map_source_key = None
    map_reused_frames = 0

    native_clip_idx = 0
    per_clip_decoded_frames = [0 for _ in native_clip_paths]
    per_clip_seek_discarded_frames = [0 for _ in native_clip_paths]
    boundary_debug_frames = {0, 1, 2, 30, 300, 600, 900}
    _boundary_offset = 0
    for _count in per_clip_requested_frames[:-1]:
        _boundary_offset += _count
        boundary_debug_frames.update(
            {_boundary_offset - 2, _boundary_offset - 1, _boundary_offset, _boundary_offset + 1, _boundary_offset + 2}
        )

    def _consume_prepared_frame(prepared: PreparedFrame) -> bool:
        nonlocal native_clip_idx, pending_seek_target_100ns, seek_discarded_frames
        nonlocal decoded_frames_python, hud_frames, successful_hud_updates, successful_video_updates
        nonlocal map_uploaded_bytes_total, map_gpu_frames, gauge_gpu_frames, gauge_uploaded_bytes_total
        nonlocal gauge_upload_calls_total, gauge_full_upload_frames, gauge_region_upload_frames
        nonlocal chart_static_uploads, chart_static_bytes_total, chart_dynamic_uploads, chart_dynamic_bytes_total
        nonlocal chart_full_tobytes_total, chart_split_frames, chart_uploaded_bytes_total
        nonlocal above_map_frames, above_map_visible_frames, above_map_uploaded_bytes_total
        nonlocal t_first_frame_begin, t_first_frame_encoded, last_map_img, last_map_dst
        nonlocal last_uploaded_map_source_key, map_reused_frames

        t_c_start = time.perf_counter()
        if t_first_frame_begin == 0.0:
            t_first_frame_begin = t_c_start
        if audit_allocs_enabled:
            _aud_c_blocks0 = sys.getallocatedblocks()
            _aud_c_traced0 = tracemalloc.get_traced_memory()[0] if tracemalloc.is_tracing() else 0
        else:
            _aud_c_blocks0 = 0
            _aud_c_traced0 = 0
        frame_acct.begin_frame(prepared.frame_idx)
        frame_acct.mark("consumer_setup_and_producer_merge")
        _sync_frame_mark("producer_prepare")
        
        # Merge producer timing samples
        for k_t, v_t in prepared.timing_samples_producer.items():
            timing_samples.setdefault(k_t, []).append(v_t)
            
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
            above_exact_clusters_samples.append(prepared.above_stats.get("exact_clusters", 0))
            above_scan_fallback_clusters_samples.append(prepared.above_stats.get("scan_fallback_clusters", 0))

        # Decode step on consumer
        _sync_frame_mark("consumer_setup")
        raw_nv12: bytes | None = None
        if use_d3d11va:
            if video_timeline is not None:
                clip_pos = video_timeline.frame_to_clip(prepared.frame_idx, target_fps)
                clip_idx = clip_pos[0] if clip_pos is not None else 0
                if clip_idx != native_clip_idx:
                    if clip_idx < 0 or clip_idx >= len(video_timeline.clips):
                        return False
                    if direct_mux_enabled:
                        print(f"[AMD DIRECT MUX] source_switch {native_clip_idx + 1}->{clip_idx + 1} global_frame={prepared.frame_idx}", flush=True)
                    if not native_switch_source(
                        h_context, str(video_timeline.clips[clip_idx].path)
                    ):
                        print(f"[AMD NATIVE D3D11] Source switch failed at clip {clip_idx + 1}.", flush=True)
                        return False
                    native_clip_idx = clip_idx
                    local_start = float(getattr(
                        video_timeline.clips[clip_idx], "local_start_s", 0.0,
                    ) or 0.0)
                    if local_start > 0.0 and not native_seek_source(
                        h_context, int(round(local_start * 10_000_000))
                    ):
                        print(
                            f"[AMD NATIVE D3D11] Source range seek failed "
                            f"at clip {clip_idx + 1}.", flush=True,
                        )
                        return False
                    pending_seek_target_100ns = (
                        int(round(local_start * 10_000_000))
                        if local_start > 0.0 else None
                    )
            while True:  # Outer loop for EOF recovery
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
                    if read_status == 1 and pending_seek_target_100ns is not None:
                        sample_half_duration = max(
                            int(sample_duration.value) // 2,
                            int(round(5_000_000.0 / target_fps)),
                        )
                        if int(sample_pts.value) + sample_half_duration < pending_seek_target_100ns:
                            if not native_discard_video_sample(h_context):
                                print(
                                    "[AMD NATIVE D3D11VA] ERROR: failed to discard "
                                    "pre-range decoder sample.",
                                    flush=True,
                                )
                                return False
                            seek_discarded_frames += 1
                            if 0 <= native_clip_idx < len(per_clip_seek_discarded_frames):
                                per_clip_seek_discarded_frames[native_clip_idx] += 1
                            continue
                        pending_seek_target_100ns = None
                    break
                if read_status == 0:
                    if video_timeline is not None and getattr(video_timeline, "clip_count", 0) > 1:
                        if native_clip_idx < len(video_timeline.clips) - 1:
                            print(f"[AMD NATIVE D3D11] EOF reached early on clip {native_clip_idx + 1}, forcing switch to next clip.", flush=True)
                            next_idx = native_clip_idx + 1
                            if direct_mux_enabled:
                                print(f"[AMD DIRECT MUX] source_switch {native_clip_idx + 1}->{next_idx + 1} global_frame={prepared.frame_idx} (EOF recovery)", flush=True)
                            if not native_switch_source(h_context, str(video_timeline.clips[next_idx].path)):
                                print(f"[AMD NATIVE D3D11] Source switch failed during EOF recovery.", flush=True)
                                return False
                            native_clip_idx = next_idx
                            local_start = float(getattr(video_timeline.clips[next_idx], "local_start_s", 0.0) or 0.0)
                            if local_start > 0.0 and not native_seek_source(h_context, int(round(local_start * 10_000_000))):
                                print(f"[AMD NATIVE D3D11] Source range seek failed during EOF recovery.", flush=True)
                                return False
                            continue
                    return False
                if read_status < 0:
                    print("[AMD NATIVE D3D11VA] ERROR: native ReadSample failed.", flush=True)
                    return False
                break
            decoded_frames_python += 1
            if 0 <= native_clip_idx < len(per_clip_decoded_frames):
                per_clip_decoded_frames[native_clip_idx] += 1
            if prepared.frame_idx in boundary_debug_frames:
                reference_pts = prepared.frame_idx / target_fps
                output_pts_100ns = int(round(reference_pts * 10_000_000))
                sample_timestamps[prepared.frame_idx] = {
                    "frame_index": prepared.frame_idx,
                    "mf_pts_100ns": int(sample_pts.value),
                    "mf_pts_seconds": sample_pts.value / 10_000_000.0,
                    "cpu_reference_seconds": reference_pts,
                    "delta_ms": ((sample_pts.value / 10_000_000.0) - reference_pts) * 1000.0,
                    "duration_100ns": int(sample_duration.value),
                    "clip_index": native_clip_idx,
                    "decoder_source": native_clip_paths[native_clip_idx],
                    "output_pts_100ns": output_pts_100ns,
                    "output_pts_seconds": output_pts_100ns / 10_000_000.0,
                    "dxgi_format": int(sample_format.value),
                    "subresource": int(sample_subresource.value),
                    "texture_pointer": hex(sample_texture.value),
                }
        else:
            assert h_cpu_pipe is not None and p010_c_buf is not None
            decode_wait_start = time.perf_counter()
            rem = frame_size
            cur_ptr = p010_buf_addr
            while rem > 0:
                chunk = wintypes.DWORD(0)
                to_read = min(rem, 4 * 1024 * 1024)
                ok = kernel32.ReadFile(h_cpu_pipe, ctypes.c_void_p(cur_ptr), to_read, ctypes.byref(chunk), None)
                if not ok or chunk.value == 0:
                    break
                rem -= chunk.value
                cur_ptr += chunk.value
            decode_wait_ms = (time.perf_counter() - decode_wait_start) * 1000.0
            if rem > 0:
                print(f"[AMD NATIVE D3D11] ERROR: Incomplete CPU P010 frame read: rem={rem}", flush=True)
                return False
            timing_samples["Decode/pipe wait"].append(decode_wait_ms)
            decoded_frames_python += 1

        t_up_stage_start = time.perf_counter()
        frame_acct.mark("decode_and_read_sample")
        _sync_frame_mark("decode_read_sample")
        
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
        if prepared.gauge_region_data:
            # ── ETAP 2B: tight sub-box updates of the persistent tile ──
            gbx, gby, gbw, gbh = prepared.gauge_tile_bbox
            up_start = time.perf_counter()
            _g_calls = 0
            for reg_entry in prepared.gauge_region_data:
                g_uploaded = c_uint64(0)
                g_created = c_int(0)
                if len(reg_entry) == 8:
                    _, rbx, rby, rbw, rbh, r_ptr_int, r_stride, _ = reg_entry
                    r_ptr = ctypes.cast(r_ptr_int, POINTER(c_uint8))
                else:
                    r_bytes, rbx, rby, rbw, rbh = reg_entry[:5]
                    r_ptr = r_bytes
                    r_stride = rbw * 4
                ok_r = native_dll.telem_amd_update_gauge_region(
                    h_context, r_ptr, rbx, rby, rbw, rbh, r_stride,
                    gbw, gbh, gbx, gby,
                    byref(g_uploaded), byref(g_created),
                )
                if ok_r:
                    _g_calls += 1
                    gauge_upload_calls_total += 1
                    gauge_uploaded_bytes_total += int(g_uploaded.value)
            gauge_upload_ms = (time.perf_counter() - up_start) * 1000.0
            timing_samples["gauge_upload"].append(gauge_upload_ms)
            timing_samples["gauge_upload_calls"].append(float(_g_calls))
            if _g_calls == len(prepared.gauge_region_data):
                gauge_gpu_frames += 1
                gauge_region_upload_frames += 1
        elif prepared.gauge_data is not None:
            if len(prepared.gauge_data) == 8:
                _, gw, gh, gx, gy, g_ptr_int, g_stride, _ = prepared.gauge_data
                g_ptr = ctypes.cast(g_ptr_int, POINTER(c_uint8))
            else:
                g_bytes, gw, gh, gx, gy = prepared.gauge_data[:5]
                g_ptr = g_bytes
                g_stride = gw * 4
            g_uploaded = c_uint64(0)
            g_created = c_int(0)
            up_start = time.perf_counter()
            ok = native_dll.telem_amd_update_gauge(
                h_context, g_ptr, gw, gh, g_stride, gx, gy, byref(g_uploaded), byref(g_created),
            )
            gauge_upload_ms = (time.perf_counter() - up_start) * 1000.0
            timing_samples["gauge_upload"].append(gauge_upload_ms)
            timing_samples["gauge_upload_calls"].append(1.0)
            if ok:
                gauge_gpu_frames += 1
                gauge_upload_calls_total += 1
                gauge_full_upload_frames += 1
                gauge_uploaded_bytes_total += int(g_uploaded.value)

        # Upload Above Regions
        if map_above_layout is not None:
            t_dispatch_start = time.perf_counter()
            if (
                isinstance(prepared.above_regions, tuple)
                and len(prepared.above_regions) == 7
                and prepared.above_regions[0] == "BATCHED"
            ):
                _, row_table_ptr_val, r_stride, rects_buf, reg_count, r_bytes_tot, _ = prepared.above_regions
                row_table_ptr = ctypes.cast(row_table_ptr_val, POINTER(c_void_p))
                t_r_start = time.perf_counter()
                r_ok = native_dll.telem_amd_update_above_regions_batch(
                    h_context, row_table_ptr, r_stride, rects_buf, reg_count
                )
                above_up_ms = (time.perf_counter() - t_r_start) * 1000.0
                if r_ok:
                    above_map_uploaded_bytes_total += r_bytes_tot
                timing_samples["above_region_upload"].append(above_up_ms)
                timing_samples["above_upload_buffer_prepare"].append(0.0)
                above_map_frames += 1
                if reg_count > 0:
                    above_map_visible_frames += 1
            else:
                reg_count = len(prepared.above_regions)
                native_dll.telem_amd_update_above_regions_count(h_context, reg_count)
                above_up_ms = 0.0
                above_buf_prep_ms = 0.0
                for r_idx, reg_entry in enumerate(prepared.above_regions):
                    if len(reg_entry) == 5:
                        rx, ry, rw, rh, r_bytes = reg_entry
                        t_prep_start = time.perf_counter()
                        r_ptr = _above_region_pointer(r_bytes, above_upload_buffer_mode)
                        above_buf_prep_ms += (time.perf_counter() - t_prep_start) * 1000.0
                        r_stride = rw * 4
                        r_len = len(r_bytes)
                    else:
                        rx, ry, rw, rh, _, r_ptr_int, r_stride, _ = reg_entry
                        r_ptr = ctypes.cast(r_ptr_int, POINTER(c_uint8))
                        r_len = rw * rh * 4

                    t_r_start = time.perf_counter()
                    r_ok = native_dll.telem_amd_update_above_region(
                        h_context, r_idx, r_ptr, rw, rh, r_stride, rx, ry
                    )
                    above_up_ms += (time.perf_counter() - t_r_start) * 1000.0
                    if r_ok:
                        above_map_uploaded_bytes_total += r_len
                timing_samples["above_region_upload"].append(above_up_ms)
                timing_samples["above_upload_buffer_prepare"].append(above_buf_prep_ms)
                above_map_frames += 1
                if reg_count > 0:
                    above_map_visible_frames += 1

            dispatch_ms = (time.perf_counter() - t_dispatch_start) * 1000.0
            n_ms = c_double(0.0)
            sub_ms = c_double(0.0)
            sub_calls = c_uint(0)
            if hasattr(native_dll, "telem_amd_get_above_region_timings"):
                native_dll.telem_amd_get_above_region_timings(
                    h_context, byref(n_ms), byref(sub_ms), byref(sub_calls)
                )
            native_region_ms = n_ms.value
            subresource_cpu_ms = sub_ms.value
            subresource_calls = float(sub_calls.value)

            extract_ms = float(prepared.above_stats.get("extract_ms", 0.0))
            python_control_ms = extract_ms + max(0.0, dispatch_ms - native_region_ms)
            region_pipeline_ms = extract_ms + dispatch_ms

            timing_samples["region_pipeline_total"].append(region_pipeline_ms)
            timing_samples["python_control_total"].append(python_control_ms)
            timing_samples["native_region_total"].append(native_region_ms)
            timing_samples["update_subresource_cpu"].append(subresource_cpu_ms)
            timing_samples["update_subresource_calls"].append(subresource_calls)

        # Upload AFTER-MAP Charts (ETAP 1B)
        if after_map_chart_gpu and prepared.after_map_chart_captures:
            for tile in prepared.after_map_chart_captures:
                if not tile.is_valid:
                    continue
                if tile.static_bytes is not None and tile.static_width > 0 and tile.static_height > 0:
                    st_uploaded = c_uint64(0)
                    st_created = c_int(0)
                    bx, by, _, _ = tile.bbox
                    native_dll.telem_amd_update_after_map_chart_static(
                        h_context, tile.slot, tile.static_bytes, tile.static_width, tile.static_height,
                        tile.static_stride, bx, by, byref(st_uploaded), byref(st_created),
                    )
                if tile.cursor_bytes is not None and tile.cursor_width > 0 and tile.cursor_height > 0:
                    c_up = c_uint64(0)
                    lx, ly = tile.cursor_local
                    native_dll.telem_amd_update_after_map_chart_dynamic(
                        h_context, tile.slot, 0, tile.cursor_bytes, tile.cursor_width, tile.cursor_height,
                        tile.cursor_stride, lx, ly, byref(c_up),
                    )
                if tile.value_bytes is not None and tile.value_width > 0 and tile.value_height > 0:
                    v_up = c_uint64(0)
                    lx, ly = tile.value_local
                    native_dll.telem_amd_update_after_map_chart_dynamic(
                        h_context, tile.slot, 1, tile.value_bytes, tile.value_width, tile.value_height,
                        tile.value_stride, lx, ly, byref(v_up),
                    )

        # Upload Map
        if prepared.map_geometry is not None:
            dst_x, dst_y, src_w, src_h, out_w, out_h = prepared.map_geometry
            native_dll.telem_amd_set_map_geometry(
                h_context, dst_x, dst_y, src_w, src_h, out_w, out_h,
            )
        if prepared.map_data is not None:
            if len(prepared.map_data) == 7:
                _, mw, mh, mdst, m_ptr_int, m_stride, _ = prepared.map_data
                m_ptr = ctypes.cast(m_ptr_int, POINTER(c_uint8)) if m_ptr_int else prepared.map_data[0]
            else:
                m_bytes, mw, mh, mdst = prepared.map_data[:4]
                m_ptr = m_bytes
                m_stride = mw * 4
            last_map_img = prepared.last_map_img
            last_map_dst = prepared.last_map_dst
            if gpu_map_rotate:
                native_dll.telem_amd_set_map_heading(h_context, c_float(prepared.map_heading))

            # ETAP 5D: GPU Texture Reuse / conditional upload when source bitmap is identical
            map_source_key = getattr(prepared, "map_crop_key", None)
            skip_upload = (
                map_source_reuse_enabled
                and map_source_key is not None
                and map_source_key == last_uploaded_map_source_key
                and map_gpu_frames > 0
            )

            if not skip_upload:
                m_uploaded = c_uint64(0)
                m_created = c_int(0)
                ok = native_dll.telem_amd_update_map(
                    h_context, m_ptr, mw, mh, m_stride, byref(m_uploaded), byref(m_created),
                )
                if ok:
                    last_uploaded_map_source_key = map_source_key
                    map_uploaded_bytes_total += int(m_uploaded.value)
                    map_gpu_frames += 1
            else:
                map_reused_frames += 1
                map_gpu_frames += 1

        # ETAP 2A FIX: run the start-of-frame HUD-canvas clears (previous
        # ABOVE regions + previous AFTER-MAP gauge tile) BEFORE the below-canvas
        # dirty rects reach telem_amd_update_hud_regions, so pixels erased
        # under the previous gauge tile are restored by this frame's upload
        # instead of being destroyed by it.  The clears consume their state;
        # the internal ClearPreviousAboveMap() inside telem_amd_process_frame
        # then no-ops — each clear still runs exactly once per frame.
        if (after_map_gauge_gpu and (
                prepared.gauge_data is not None or prepared.gauge_region_data
                or prepared.gauge_clear_only)) or (lean_gpu_enabled and prepared.lean_active):
            native_dll.telem_amd_run_early_clears(h_context)

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
                    for entry in prepared.dirty_rect_slices:
                        if len(entry) == 8:
                            x, y, rect_w, rect_h, _, src_ptr_int, c_stride, _ = entry
                            dst_base = hud_backing_address + y * c_stride + x * 4
                            for r in range(rect_h):
                                ctypes.memmove(dst_base + r * c_stride, src_ptr_int + r * c_stride, rect_w * 4)
                        else:
                            x, y, rect_w, rect_h, r_bytes = entry[:5]
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
            assert p010_c_buf is not None
            up_ms = ctypes.c_double(0.0)
            video_update_ok = native_dll.telem_amd_update_video_frame_p010(
                h_context, p010_c_buf, video_width, video_height, video_width * 2, ctypes.byref(up_ms)
            )
            if not video_update_ok:
                print(f"[AMD NATIVE D3D11] ERROR: telem_amd_update_video_frame_p010 failed on frame {prepared.frame_idx}", flush=True)
                return False
            successful_video_updates += 1

        t_up_stage_ms = (time.perf_counter() - t_up_stage_start) * 1000.0
        queue_truth.mark(prepared.frame_idx, "upload_end")
        timing_samples["consumer_upload"].append(t_up_stage_ms)
        frame_acct.mark("consumer_upload")
        _sync_frame_mark("upload")

        # ETAP 2G: GPU lean indicator dynamic affine transform
        if prepared.lean_active and prepared.lean_transform is not None:
            _ang, _px, _py, _spx, _spy, _dx, _dy, _tw, _th = prepared.lean_transform
            native_dll.telem_amd_set_lean_transform(
                h_context,
                c_float(_ang),
                c_float(_px),
                c_float(_py),
                c_float(_spx),
                c_float(_spy),
                c_uint(_dx),
                c_uint(_dy),
                c_uint(_tw),
                c_uint(_th),
            )

        # Process Frame
        t_native_start = time.perf_counter()
        queue_truth.mark(prepared.frame_idx, "native_call_begin")
        ret = native_dll.telem_amd_process_frame(h_context, prepared.frame_idx, 1 if hud_enabled else 0)
        t_native_ms = (time.perf_counter() - t_native_start) * 1000.0
        queue_truth.mark(prepared.frame_idx, "native_call_end")
        timing_samples["consumer_native_call"].append(t_native_ms)
        frame_acct.mark("native_process_frame")
        _sync_frame_mark("native_process_call")
        if not ret:
            print(f"[AMD NATIVE D3D11] ERROR: telem_amd_process_frame failed on frame {prepared.frame_idx}", flush=True)
            return False

        chk_frame_env = os.environ.get("AMD_DUMP_CHECKPOINT_FRAME")
        if chk_frame_env is not None and prepared.frame_idx == int(chk_frame_env):
            chk_stage = os.environ.get("AMD_DUMP_CHECKPOINT_STAGE", "03_amf_input").encode("utf-8")
            chk_path = os.environ.get("AMD_DUMP_CHECKPOINT_PATH", "scratch/chk.png")
            native_dll.telem_amd_dump_checkpoint(h_context, prepared.frame_idx, chk_stage, chk_path)

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
        _sync_frame_mark("consumer_post_native")
        queue_truth.mark(prepared.frame_idx, "consumer_end")
        frame_acct.mark("consumer_post_native_and_bookkeeping")
        frame_acct.end_frame()
        pipeline_total_ms = (t_c_end - t_c_start) * 1000.0
        timing_samples["pipeline_total"].append(pipeline_total_ms)

        if audit_allocs_enabled:
            audit_alloc_frames.append({
                "frame": prepared.frame_idx,
                "producer_alloc_blocks": prepared.timing_samples_producer.get("producer_alloc_blocks", 0.0),
                "producer_alloc_traced_bytes": prepared.timing_samples_producer.get("producer_alloc_traced_bytes", 0.0),
                "consumer_alloc_blocks": float(sys.getallocatedblocks() - _aud_c_blocks0),
                "consumer_alloc_traced_bytes": float(
                    (tracemalloc.get_traced_memory()[0] - _aud_c_traced0) if tracemalloc.is_tracing() else 0.0
                ),
            })

        if prepared.frame_idx in {0, 1, 30, 100, 300, 500, 750, 900, 1130}:
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
        expected_progress_frames = total_frames
        if (prepared.frame_idx + 1) % progress_interval == 0 or (prepared.frame_idx + 1) == expected_progress_frames:
            elapsed = time.time() - start_time
            fps = (prepared.frame_idx + 1) / elapsed if elapsed > 0 else 0
            eta = (expected_progress_frames - (prepared.frame_idx + 1)) / fps if fps > 0 else 0
            pct = int(((prepared.frame_idx + 1) / expected_progress_frames) * 100)
            m, s = divmod(int(elapsed), 60)
            em, es = divmod(int(eta), 60)
            stats_str = f"Frame: {prepared.frame_idx+1}/{expected_progress_frames} | {pct}% | {fps:.1f} FPS | {m:02d}:{s:02d} elapsed, ETA {em:02d}:{es:02d}"
            if progress_cb:
                progress_cb(pct, stats_str)
            progress_tracker.frame(prepared.frame_idx + 1, elapsed, fps)
            if time.time() - last_hud_report_holder[0] >= 1.0:
                last_hud_report_holder[0] = time.time()
                print(f"[AMD NATIVE D3D11] Frame {prepared.frame_idx+1}/{expected_progress_frames} ({fps:.1f} FPS)", flush=True)

        return True

    # GUI phase-report: HUD preparation finished, frame rendering begins.
    progress_tracker.hud_complete_report()

    # Main Execution Switch: ASYNC (Producer-Consumer) vs SYNC (Diagnostic)
    try:
        if pipeline_mode == "ASYNC":
            q_depth = max(1, int(os.getenv("AMD_QUEUE_DEPTH", "2")))
            frame_queue: queue.Queue = queue.Queue(maxsize=q_depth)
            queue_truth.configure(q_depth)
            cancel_evt = cancel_event if cancel_event is not None else threading.Event()
            producer_error: list[Exception] = []

            def producer_worker():
                try:
                    for f_idx in range(total_frames):
                        if cancel_evt.is_set():
                            break
                        prep = _prepare_frame_cpu(f_idx)
                        t_put_start = queue_truth.put_begin(f_idx, frame_queue.qsize())
                        while not cancel_evt.is_set():
                            try:
                                frame_queue.put(prep, timeout=0.05)
                                t_put_ms = (time.perf_counter() - t_put_start) * 1000.0
                                queue_truth.put_end(f_idx, t_put_start, frame_queue.qsize())
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
                    t_get_start = queue_truth.get_begin(consumed_count, frame_queue.qsize())
                    item = None
                    while not cancel_evt.is_set():
                        try:
                            item = frame_queue.get(timeout=0.05)
                            t_get_ms = (time.perf_counter() - t_get_start) * 1000.0
                            queue_truth.get_end(consumed_count, t_get_start, frame_queue.qsize())
                            timing_samples["consumer_queue_wait"].append(t_get_ms)
                            break
                        except queue.Empty:
                            if producer_error:
                                raise producer_error[0]
                            continue
                    if cancel_evt.is_set():
                        print("[AMD NATIVE D3D11] Export cancelled by user.", flush=True)
                        _cleanup_native_resources()
                        _abort_direct_mux()
                        return False
                    if item is _END_OF_STREAM:
                        break
                    assert isinstance(item, PreparedFrame)
                    assert item.frame_idx == consumed_count, f"Frame order violation: expected {consumed_count}, got {item.frame_idx}"
                    queue_truth.mark(item.frame_idx, "upload_begin")
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
            _ft_prev_end: float | None = None
            for f_idx in range(total_frames):
                if cancel_event is not None and cancel_event.is_set():
                    print("[AMD NATIVE D3D11] Export cancelled by user.", flush=True)
                    _cleanup_native_resources()
                    _abort_direct_mux()
                    return False
                if sync_frame_accounting_enabled:
                    _sync_parent_start = time.perf_counter_ns()
                    sync_frame_current = {
                        "frame": f_idx,
                        "last_ns": _sync_parent_start,
                        "stages": {},
                    }
                if frame_trace_enabled:
                    _ft_t0 = time.perf_counter()
                prep = _prepare_frame_cpu(f_idx)
                if frame_trace_enabled:
                    _ft_t1 = time.perf_counter()
                timing_samples["producer_queue_wait"].append(0.0)
                timing_samples["consumer_queue_wait"].append(0.0)
                ok = _consume_prepared_frame(prep)
                if sync_frame_accounting_enabled and sync_frame_current is not None:
                    _sync_parent_end = time.perf_counter_ns()
                    _sync_sum = sum(sync_frame_current["stages"].values())
                    sync_frame_records.append({
                        "frame": f_idx,
                        "parent_ms": (_sync_parent_end - _sync_parent_start) / 1_000_000.0,
                        "stages": dict(sync_frame_current["stages"]),
                        "residual_ms": (_sync_parent_end - _sync_parent_start) / 1_000_000.0 - _sync_sum,
                    })
                    sync_frame_current = None
                if frame_trace_enabled:
                    _ft_t2 = time.perf_counter()
                    _ft_gap = (
                        (_ft_t0 - _ft_prev_end) * 1000.0 if _ft_prev_end is not None else 0.0
                    )
                    _ft_prev_end = _ft_t2
                    _row: dict[str, Any] = {
                        "frame": f_idx,
                        "frame_total_ms": (_ft_t2 - _ft_t0) * 1000.0,
                        "producer_ms": (_ft_t1 - _ft_t0) * 1000.0,
                        "consumer_ms": (_ft_t2 - _ft_t1) * 1000.0,
                        "inter_frame_gap_ms": _ft_gap,
                    }
                    for _k in ("Telemetry/frame_data", "compose_overlay", "above_total",
                               "above_compose", "above_region_to_bytes", "above_region_upload",
                               "map_cpu_upload", "HUD dirty extract", "PIL/buffer preparation",
                               "chart_cpu_tobytes", "chart_dynamic_tobytes", "gauge_tobytes"):
                        _v = timing_samples.get(_k)
                        if _v:
                            _row["p_" + _k] = _v[-1]
                    for _k in ("MF ReadSample/decode availability", "consumer_upload",
                               "consumer_native_call", "VideoProcessor CPU submit",
                               "VideoProcessor GPU completion", "GPU wait/synchronization",
                               "AMF submit/backpressure", "AMF QueryOutput", "Packet write",
                               "pipeline_total"):
                        _v = timing_samples.get(_k)
                        if _v:
                            _row["c_" + _k] = _v[-1]
                    if bottleneck_proof_enabled:
                        _dec_ms = timing_samples.get("MF ReadSample/decode availability", [0.0])[-1]
                        _comp_ms = (
                            timing_samples.get("VideoProcessor CPU submit", [0.0])[-1]
                            + timing_samples.get("consumer_upload", [0.0])[-1]
                        )
                        _amf_sub = timing_samples.get("AMF submit/backpressure", [0.0])[-1]
                        _amf_out = timing_samples.get("AMF QueryOutput", [0.0])[-1]
                        _mux_w = timing_samples.get("Packet write", [0.0])[-1]
                        _row["decode_wait_ms"] = _dec_ms
                        _row["prepare_compositor_ms"] = _comp_ms
                        _row["amf_submit_ms"] = _amf_sub
                        _row["amf_wait_output_ms"] = _amf_out
                        _row["mux_write_ms"] = _mux_w
                        _row["total_frame_wall_ms"] = _row["frame_total_ms"]
                        _row["map_ms"] = timing_samples.get("map_cpu_upload", [0.0])[-1]
                        _row["charts_ms"] = (
                            timing_samples.get("chart_cpu_tobytes", [0.0])[-1]
                            + timing_samples.get("chart_dynamic_tobytes", [0.0])[-1]
                        )
                        _row["gauge_ms"] = timing_samples.get("gauge_tobytes", [0.0])[-1]
                        _row["above_ms"] = timing_samples.get("above_total", [0.0])[-1]
                        _row["vp_gpu_ms"] = timing_samples.get("VideoProcessor GPU completion", [0.0])[-1]
                    frame_trace_rows.append(_row)
                if not ok:
                    # EOS reached normally from decoder
                    break

        t_video_render_end = time.perf_counter()
        _tile_stats = get_map_tile_stats()
        print(f"[AMD Map Tile Stats] {_tile_stats}", flush=True)
        # GUI phase-report: all frames rendered, final flush/mux starts.
        if on_render_progress is not None:
            progress_tracker._emit(phase="finalize", internal=0.0, label="Finalizacja...", force=True,
                                   elapsed=time.time() - start_time)

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

        c_q_submitted = c_uint64(0)
        c_q_received = c_uint64(0)
        c_q_in_flight = c_uint64(0)
        c_q_max_in_flight = c_uint64(0)
        c_q_query_calls = c_uint64(0)
        c_q_input_full = c_uint64(0)
        c_q_not_ready = c_uint64(0)
        c_q_retries = c_uint64(0)
        c_q_wait_ms = ctypes.c_double(0.0)
        if hasattr(native_dll, "telem_amd_get_queue_stats"):
            native_dll.telem_amd_get_queue_stats(
                h_context,
                byref(c_q_submitted),
                byref(c_q_received),
                byref(c_q_in_flight),
                byref(c_q_max_in_flight),
                byref(c_q_query_calls),
                byref(c_q_input_full),
                byref(c_q_not_ready),
                byref(c_q_retries),
                byref(c_q_wait_ms),
            )
        if os.getenv("AMD_AMF_QUEUE_DIAG") == "1" or os.getenv("AMD_AMF_DIAG") == "1":
            print("\n[AMD AMF QUEUE DIAGNOSTICS]", flush=True)
            print(f"  submitted_frames:       {c_q_submitted.value}", flush=True)
            print(f"  received_frames:        {c_q_received.value}", flush=True)
            print(f"  in_flight_frames:       {c_q_in_flight.value}", flush=True)
            print(f"  max_in_flight:          {c_q_max_in_flight.value}", flush=True)
            print(f"  query_output_calls:     {c_q_query_calls.value}", flush=True)
            print(f"  input_full_count:       {c_q_input_full.value}", flush=True)
            print(f"  output_not_ready_count: {c_q_not_ready.value}", flush=True)
            print(f"  retry_count:            {c_q_retries.value}", flush=True)
            print(f"  consumer_wait_ms:       {c_q_wait_ms.value:.3f}", flush=True)

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
    except Exception:
        if direct_mux_enabled and not direct_mux_completed:
            _abort_direct_mux()
        raise
    finally:
        set_map_network_allowed(True)
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
    elif direct_mux_enabled and proc_mux is not None:
        # ── DIRECT MP4 LIVE MUX FINALIZATION ──
        t_mux_begin = time.perf_counter()
        print("[AMD NATIVE D3D11] Finalizing direct MP4 live mux...", flush=True)
        if pump_thread is not None:
            pump_thread.join(timeout=30.0)
        try:
            proc_mux.wait(timeout=30.0)
        except subprocess.TimeoutExpired:
            proc_mux.kill()
            proc_mux.wait()
        if stderr_thread is not None:
            stderr_thread.join(timeout=5.0)
        t_mux_end = time.perf_counter()
        mux_elapsed_ms = (t_mux_end - t_mux_begin) * 1000.0
        timing_samples["Audio mux"].append(mux_elapsed_ms)

        if proc_mux.returncode != 0 or mux_pump_error:
            mux_err_str = b"".join(mux_stderr_lines).decode(errors="replace").strip()
            print(
                f"[AMD NATIVE D3D11] ERROR: Direct MP4 live mux failed (rc={proc_mux.returncode}, pump={mux_pump_error})!\n"
                f"{mux_err_str[-4000:]}",
                flush=True,
            )
            if os.path.exists(output_part_str):
                try: os.remove(output_part_str)
                except OSError: pass
            if audio_concat_path is not None and audio_concat_path.exists():
                try: audio_concat_path.unlink()
                except OSError: pass
            return False

        if not os.path.exists(output_part_str) or os.path.getsize(output_part_str) == 0:
            print(f"[AMD NATIVE D3D11] ERROR: Direct MP4 output {output_part_str} is missing or empty!", flush=True)
            if audio_concat_path is not None and audio_concat_path.exists():
                try: audio_concat_path.unlink()
                except OSError: pass
            return False

        # Probe sanity check on .part before atomic rename
        final_probe = _probe_video_summary(ffmpeg_exe, output_part_str)
        muxed_frames = _stream_frame_count(final_probe, "video")
        audio_present = any(
            stream.get("codec_type") == "audio" for stream in final_probe.get("streams", [])
        )
        if muxed_frames == 0:
            print(f"[AMD NATIVE D3D11] ERROR: Direct MP4 output has 0 muxed video frames!", flush=True)
            if os.path.exists(output_part_str):
                try: os.remove(output_part_str)
                except OSError: pass
            if audio_concat_path is not None and audio_concat_path.exists():
                try: audio_concat_path.unlink()
                except OSError: pass
            return False

        # Atomic rename .part -> final .mp4
        if os.path.exists(output_file_str):
            try: os.remove(output_file_str)
            except OSError: pass
        os.replace(output_part_str, output_file_str)
        if audio_concat_path is not None and audio_concat_path.exists():
            try: audio_concat_path.unlink()
            except OSError: pass
        direct_mux_completed = True
        print(f"[AMD NATIVE D3D11] Direct MP4 Mux complete. Final output: {output_file_str}", flush=True)
    else:
        # ── FALLBACK FILE REMUX ──
        if not os.path.exists(temp_h265) or os.path.getsize(temp_h265) == 0:
            print(f"[AMD NATIVE D3D11] ERROR: Raw bitstream {temp_h265} is missing or empty!", flush=True)
            return False

        audio_input = input_file_str
        audio_args: list[str] = ["-i", audio_input]
        audio_concat_path: Optional[Path] = None
        if video_timeline is not None and getattr(video_timeline, "clip_count", 0) > 1:
            audio_concat_path = Path(output_file_str).with_suffix(".audio.concat.txt")
            with audio_concat_path.open("w", encoding="utf-8", newline="\n") as concat_file:
                for clip in video_timeline.clips:
                    concat_file.write("file '" + str(clip.path).replace("'", "'\\''") + "'\n")
                    local_start = float(getattr(clip, "local_start_s", 0.0) or 0.0)
                    if local_start > 0.0:
                        concat_file.write(f"inpoint {local_start:.9f}\n")
                    local_end = float(getattr(clip, "local_end_s", clip.duration_s))
                    source_duration = float(getattr(clip, "source_duration_s", 0.0) or 0.0)
                    if source_duration <= 0.0 or local_end < source_duration - 1e-6:
                        concat_file.write(f"outpoint {local_end:.9f}\n")
            audio_args = ["-f", "concat", "-safe", "0", "-i", str(audio_concat_path)]
        elif video_timeline is not None and getattr(video_timeline, "clip_count", 0) == 1:
            local_start = float(getattr(video_timeline.clips[0], "local_start_s", 0.0) or 0.0)
            if local_start > 0.0:
                audio_args = ["-ss", f"{local_start:.6f}", "-i", audio_input]

        cmd_mux = [
            ffmpeg_exe, "-y", "-i", temp_h265, *audio_args,
            "-map", "0:v", "-map", "1:a?", "-t", f"{duration_s:.6f}",
            "-c:v", "copy", "-c:a", "copy", output_file_str,
        ]

        print("[AMD NATIVE D3D11] Muxing encoded video stream + audio (-c:v copy -c:a copy)...", flush=True)
        t_mux_begin = time.perf_counter()
        proc = subprocess.run(cmd_mux, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        t_mux_end = time.perf_counter()
        mux_elapsed_ms = (t_mux_end - t_mux_begin) * 1000.0
        timing_samples["Audio mux"].append(mux_elapsed_ms)
        if proc.returncode != 0:
            mux_error = (proc.stderr or b"").decode(errors="replace").strip()
            print(
                "[AMD NATIVE D3D11] ERROR: FFmpeg remux failed!\n"
                f"{mux_error[-4000:]}",
                flush=True,
            )
            if os.path.exists(temp_h265):
                try: os.remove(temp_h265)
                except OSError: pass
            return False
        else:
            print(f"[AMD NATIVE D3D11] Remux complete. Final output: {output_file_str}", flush=True)
            if os.path.exists(temp_h265):
                for _ in range(10):
                    try:
                        os.remove(temp_h265)
                        break
                    except OSError:
                        time.sleep(0.05)
        if audio_concat_path is not None and audio_concat_path.exists():
            try:
                audio_concat_path.unlink()
            except OSError:
                pass

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

    if render_debug_enabled():
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
        print(f"  video_render_wall_ms:              {video_render_wall_ms:.3f} ms ({video_render_wall_ms/1000.0:.3f} s)", flush=True)
        print(f"  mux_wall_ms:                       {mux_wall_ms:.3f} ms ({mux_wall_ms/1000.0:.3f} s)", flush=True)
        print(f"  TOTAL_FROM_EXPORT_START_ms:        {total_from_export_start_ms:.3f} ms ({total_from_export_start_ms/1000.0:.3f} s)", flush=True)
        print(f"  RENDER FPS:                        {render_fps:.3f} fps", flush=True)
        print(f"  USER EFFECTIVE FPS:                {effective_fps:.3f} fps", flush=True)

    print("=== RENDER COMPLETE ===", flush=True)
    print(f"Frames: {c_rec.value}", flush=True)
    print(f"HUD prepare: {progress_tracker.hud_actual_estimate:.3f} s", flush=True)
    print(f"Video encode: {video_render_wall_ms / 1000.0:.3f} s", flush=True)
    print(f"Finalize: {mux_wall_ms / 1000.0:.3f} s", flush=True)
    print(f"Total: {total_from_export_start_ms / 1000.0:.3f} s", flush=True)
    print(f"Render FPS: {render_fps:.3f}", flush=True)
    print(f"Effective FPS: {effective_fps:.3f}", flush=True)

    profile = {
        "schema_version": 1,
        "benchmark": {
            "mode": resolve_amd_config().get("benchmark_mode", "DIRECT_RUNTIME"),
            "config": resolve_amd_config(),
            "config_fingerprint": make_benchmark_fingerprint(
                resolve_amd_config(),
                video=os.getenv("AMD_BENCHMARK_VIDEO", input_file_str),
                fit=os.getenv("AMD_BENCHMARK_FIT"),
                layout=os.getenv("AMD_BENCHMARK_LAYOUT"),
                layout_sha256=os.getenv("AMD_BENCHMARK_LAYOUT_SHA256"),
                output=output_file_str,
            ),
            "video": os.getenv("AMD_BENCHMARK_VIDEO", input_file_str),
            "fit": os.getenv("AMD_BENCHMARK_FIT"),
            "layout": os.getenv("AMD_BENCHMARK_LAYOUT"),
            "layout_sha256": os.getenv("AMD_BENCHMARK_LAYOUT_SHA256"),
            "output_path": output_file_str,
            "output_drive": Path(output_file_str).drive,
        },
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
            "per_clip": [
                {
                    "clip_index": idx,
                    "path": native_clip_paths[idx],
                    "requested_frames": (
                        per_clip_requested_frames[idx]
                        if idx < len(per_clip_requested_frames) else 0
                    ),
                    "decoded_frames": per_clip_decoded_frames[idx],
                    "submitted_frames": per_clip_decoded_frames[idx],
                    "encoded_frames": per_clip_decoded_frames[idx],
                    "seek_discarded_frames": per_clip_seek_discarded_frames[idx],
                }
                for idx in range(len(native_clip_paths))
            ],
            "cadence_gpu": chart_gpu_frames.get("fit_cadence_text", 0),
            "hr_gpu": chart_gpu_frames.get("fit_heart_rate_text", 0),
            "map_gpu": map_gpu_frames,
            "map_reused_frames": map_reused_frames,
            "map_uploaded_bytes": map_uploaded_bytes_total,
            "seek_discarded_frames": seek_discarded_frames,
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
            "above_dirty_mode": above_dirty_mode,
            "above_upload_buffer_mode": above_upload_buffer_mode,
            "above_exact_clusters": (
                _value_summary([float(v) for v in above_exact_clusters_samples])
                if above_exact_clusters_samples else None
            ),
            "above_scan_fallback_clusters": (
                _value_summary([float(v) for v in above_scan_fallback_clusters_samples])
                if above_scan_fallback_clusters_samples else None
            ),
            "above_exact_fallback_reason": dict(above_exact_counters["fallback_reason"]),
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
        "etap1a": {
            "after_map_chart_capture_diag": after_map_chart_capture_diag,
            "before_map_chart_keys": sorted(before_map_chart_keys),
            "after_map_chart_keys": sorted(after_map_chart_keys),
            "gpu_chart_keys_before_map": sorted(gpu_chart_keys_before_map),
            "gpu_chart_keys_after_map": sorted(gpu_chart_keys_after_map),
            "after_map_captures_performed": after_map_captures_performed,
            "native_after_map_blend_active": False,
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
            "etap2b_dynamic_rects": bool(gauge_dynamic_rects),
            "etap2b_gauge_upload_calls_total": gauge_upload_calls_total,
            "etap2b_gauge_full_upload_frames": gauge_full_upload_frames,
            "etap2b_gauge_region_upload_frames": gauge_region_upload_frames,
            "gauge_gpu_to_cpu_readback": 0,
            "gauge_ab_readback": gauge_ab_readback,
            "gauge_ab": (
                {key: _value_summary(values) for key, values in gauge_ab_results.items() if values}
                if gauge_ab_readback and gauge_ab_results["mae"] else None
            ),
        },
        "etap5a": overlay_profiler.summary(),
        "etap5o": {"amf_mode": amf_mode, "amf_diag_enabled": amf_diag_enabled},
        "etap5p": {
            "enabled": bool(fa_enabled or os.getenv("AMD_PRODUCTION_ACCOUNTING", "0") == "1"),
            "producer_exclusive_accounting": _exclusive_timing_accounting(
                timing_samples["producer_prepare"],
                {
                    # Accounting is debug-gated.  Keep the normal production
                    # profile writer total even when the optional stage clocks
                    # were not collected.
                    "telemetry_resolve": timing_samples.get("producer_active.telemetry_resolve", []),
                    "below_map_compose": timing_samples.get("producer_active.below_map_compose", []),
                    "above_map_compose_and_capture": timing_samples.get("producer_active.above_map_compose_and_capture", []),
                    "map_cpu_preparation": timing_samples.get("producer_active.map_cpu_preparation", []),
                    "dirty_region_and_buffer_preparation": timing_samples.get("producer_active.dirty_region_and_buffer_preparation", []),
                    "PreparedFrame_construction": timing_samples.get("producer_active.PreparedFrame_construction_boundary", []),
                },
            ),
            "consumer_exclusive_accounting": _frame_accounting_summary(frame_acct),
            "production_widget_accounting": production_accounting_summary(),
            "above_compose_accounting": _production_above_accounting(production_accounting_summary()),
            "clock": "perf_counter; producer/consumer timestamps are wall-clock thread-local intervals; native CSV uses QueryPerformanceCounter; GPU CSV uses D3D11 timestamp frequency",
        },
        "etap5q": {
            "queue_truth": queue_truth.summary(total_frames),
            "native_breakdown": {
                "source": "<output>.frame_accounting.csv when AMD_NATIVE_FRAME_ACCOUNTING=1",
                "instrumentation": "native QPC/steady_clock wall timings; no synchronized GPU readback",
                "classification": "CPU API-call wall / CPU active / CPU wait; GPU execution is not inferred from CPU wall",
            },
        },
        "etap5t": {
            "sync_frame_active": _sync_frame_accounting_summary(sync_frame_records),
            "enabled": sync_frame_accounting_enabled,
        },
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
        "etap2c_gauge_regions": {
            "mode": gauge_region_mode,
            "auto_regions_default_on": _env_flag("AMD_GAUGE_AUTO_REGIONS", True),
            "full_refresh_n": gauge_full_refresh_n,
            "epoch_changes": int(gauge_region_state.get("epoch_changes", 0)),
            "last_epoch_mode": gauge_region_state.get("mode", "-"),
            "oracle_enabled": bool(_gauge_oracle_state["enabled"]),
            "oracle_frames": _gauge_oracle_state["frames"],
            "oracle_region_frames": _gauge_oracle_state["region_frames"],
            "oracle_full_frames": _gauge_oracle_state["full_frames"],
            "oracle_changed_pixels": _gauge_oracle_state["changed_pixels"],
            "oracle_covered_pixels": _gauge_oracle_state["covered_pixels"],
            "missed_dynamic_pixels": _gauge_oracle_state["missed_dynamic_pixels"],
            "worst_frame_missed": _gauge_oracle_state["worst_frame_missed"],
            "violations": list(_gauge_oracle_state["violations"]),
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
        "audit_allocations": (
            {
                "frames": len(audit_alloc_frames),
                "producer_alloc_blocks": _value_summary([f["producer_alloc_blocks"] for f in audit_alloc_frames]),
                "producer_alloc_traced_bytes": _value_summary([f["producer_alloc_traced_bytes"] for f in audit_alloc_frames]),
                "consumer_alloc_blocks": _value_summary([f["consumer_alloc_blocks"] for f in audit_alloc_frames]),
                "consumer_alloc_traced_bytes": _value_summary([f["consumer_alloc_traced_bytes"] for f in audit_alloc_frames]),
            }
            if audit_allocs_enabled else None
        ),
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

    # ETAP 2B DIAGNOSTIC (temporary): persist gauge variability measurement.
    if _gauge_var_probe:
        try:
            _gv_records = _gauge_var_state["frames"]
            _gv_summary: dict[str, Any] = {"frames_measured": len(_gv_records)}
            _u = _gauge_var_state["union"]
            if _u is not None:
                _uh, _uw = _u.shape
                _gv_summary["tile_w"] = int(_uw)
                _gv_summary["tile_h"] = int(_uh)
                _gv_summary["union_changed_px"] = int(np.count_nonzero(_u))
                _gv_summary["union_density_pct"] = round(
                    100.0 * float(np.count_nonzero(_u)) / float(_uw * _uh), 4)
                if _u.any():
                    _uys, _uxs = np.nonzero(_u)
                    _gv_summary["union_bbox_local"] = [
                        int(_uxs.min()), int(_uys.min()),
                        int(_uxs.max() - _uxs.min() + 1),
                        int(_uys.max() - _uys.min() + 1)]
            _gv_path = output_file_str + ".gauge_variability.json"
            with open(_gv_path, "w", encoding="utf-8") as _gv_file:
                json.dump({"summary": _gv_summary,
                           "records": _gv_records}, _gv_file)
            print(
                f"[AMD NATIVE D3D11] ETAP 2B DIAGNOSTIC: gauge variability "
                f"JSON -> {_gv_path} (frames={len(_gv_records)}, "
                f"summary={_gv_summary})",
                flush=True,
            )
        except Exception as exc:
            print(
                "[AMD NATIVE D3D11] WARNING: failed to write gauge "
                f"variability JSON: {exc}",
                flush=True,
            )


    # AMD_RENDER_PATH_AUDIT_2: dump the per-frame wall-clock accounting CSV.
    if frame_trace_enabled and frame_trace_rows:
        import csv as _ft_csv
        ft_path = output_file_str + ".frame_trace.csv"
        try:
            _ft_fields: list[str] = []
            for _r in frame_trace_rows:
                for _k in _r:
                    if _k not in _ft_fields:
                        _ft_fields.append(_k)
            with open(ft_path, "w", newline="", encoding="utf-8") as ftf:
                _ft_w = _ft_csv.DictWriter(ftf, fieldnames=_ft_fields, extrasaction="ignore")
                _ft_w.writeheader()
                _ft_w.writerows(frame_trace_rows)
            print(f"[AMD NATIVE] Frame trace CSV: {ft_path}", flush=True)
        except Exception as exc:
            print(f"[AMD NATIVE] WARNING: failed to write frame trace CSV: {exc}", flush=True)

    if bottleneck_proof_enabled and frame_trace_rows:
        try:
            import numpy as _bp_np
            _total_f = len(frame_trace_rows)
            _t_wall_tot = sum(r.get("total_frame_wall_ms", r.get("frame_total_ms", 0.0)) for r in frame_trace_rows)
            _render_dur = (t_video_render_end - t_first_frame_begin) if (t_video_render_end > t_first_frame_begin) else (_t_wall_tot / 1000.0)
            _render_fps = _total_f / _render_dur if _render_dur > 0 else 0.0
            _eff_dur = time.perf_counter() - t_export_start
            _effective_fps = _total_f / _eff_dur if _eff_dur > 0 else 0.0

            _bp_keys = [
                "decode_wait_ms", "prepare_compositor_ms", "map_ms", "charts_ms",
                "gauge_ms", "above_ms", "vp_gpu_ms", "amf_submit_ms",
                "amf_wait_output_ms", "mux_write_ms", "total_frame_wall_ms"
            ]
            _metrics = {}
            for k in _bp_keys:
                vals = [r.get(k, 0.0) for r in frame_trace_rows]
                if vals:
                    arr = _bp_np.array(vals)
                    tot = float(_bp_np.sum(arr))
                    _metrics[k] = {
                        "mean": round(float(_bp_np.mean(arr)), 3),
                        "median": round(float(_bp_np.median(arr)), 3),
                        "p90": round(float(_bp_np.percentile(arr, 90)), 3),
                        "p95": round(float(_bp_np.percentile(arr, 95)), 3),
                        "p99": round(float(_bp_np.percentile(arr, 99)), 3),
                        "max": round(float(_bp_np.max(arr)), 3),
                        "pct_of_wall": round((tot / _t_wall_tot * 100.0) if _t_wall_tot > 0 else 0.0, 2),
                    }

            _quartiles = []
            _step = max(1, _total_f // 4)
            for q_idx in range(4):
                q_start = q_idx * _step
                q_end = min(_total_f, (q_idx + 1) * _step) if q_idx < 3 else _total_f
                q_rows = frame_trace_rows[q_start:q_end]
                if q_rows:
                    q_wall = sum(r.get("total_frame_wall_ms", r.get("frame_total_ms", 0.0)) for r in q_rows)
                    q_fps = len(q_rows) / (q_wall / 1000.0) if q_wall > 0 else 0.0
                    _quartiles.append({
                        "segment": f"{q_idx*25}%-{(q_idx+1)*25}%",
                        "frames": len(q_rows),
                        "fps": round(q_fps, 3),
                        "decode_wait_mean_ms": round(float(_bp_np.mean([r.get("decode_wait_ms", 0.0) for r in q_rows])), 3),
                        "compositor_mean_ms": round(float(_bp_np.mean([r.get("prepare_compositor_ms", 0.0) for r in q_rows])), 3),
                        "amf_submit_mean_ms": round(float(_bp_np.mean([r.get("amf_submit_ms", 0.0) for r in q_rows])), 3),
                        "amf_wait_output_mean_ms": round(float(_bp_np.mean([r.get("amf_wait_output_ms", 0.0) for r in q_rows])), 3),
                        "mux_write_mean_ms": round(float(_bp_np.mean([r.get("mux_write_ms", 0.0) for r in q_rows])), 3),
                    })

            _bp_data = {
                "frames": _total_f,
                "render_fps": round(_render_fps, 3),
                "effective_fps": round(_effective_fps, 3),
                "metrics": _metrics,
                "quartiles": _quartiles,
                "amf_stats": {
                    "input_full": int(c_input_full.value),
                    "retries": int(c_retries.value),
                    "dropped": int(c_dropped.value),
                    "submitted": int(c_sub.value),
                    "received": int(c_rec.value),
                },
                "direct_mux": {
                    "enabled": direct_mux_enabled,
                    "bytes": mux_pump_stats.get("bytes", 0),
                    "chunks": mux_pump_stats.get("chunks", 0),
                    "error": mux_pump_error,
                }
            }
            bp_path = output_file_str + ".bottleneck_proof.json"
            with open(bp_path, "w", encoding="utf-8") as bpf:
                json.dump(_bp_data, bpf, indent=2)
            print("=" * 95, flush=True)
            print("[TELEM BOTTLENECK PROOF SUMMARY]", flush=True)
            print(f"Frames: {_total_f} | Render FPS: {_render_fps:.3f} | Effective FPS: {_effective_fps:.3f}", flush=True)
            print(f"{'STAGE':<25} {'MEAN (ms)':<10} {'MEDIAN':<10} {'P90':<10} {'P95':<10} {'P99':<10} {'MAX':<10} {'% WALL':<8}", flush=True)
            print("-" * 95, flush=True)
            for k, m in _metrics.items():
                print(f"{k:<25} {m['mean']:<10.3f} {m['median']:<10.3f} {m['p90']:<10.3f} {m['p95']:<10.3f} {m['p99']:<10.3f} {m['max']:<10.3f} {m['pct_of_wall']:<8.2f}%", flush=True)
            print("-" * 95, flush=True)
            print("LONG-RUN QUARTILES:", flush=True)
            for q in _quartiles:
                print(f"  {q['segment']:<10}: FPS={q['fps']:<7.3f} decode={q['decode_wait_mean_ms']:<6.2f}ms comp={q['compositor_mean_ms']:<6.2f}ms amf_sub={q['amf_submit_mean_ms']:<6.2f}ms amf_out={q['amf_wait_output_mean_ms']:<6.2f}ms mux={q['mux_write_mean_ms']:<6.2f}ms", flush=True)
            print(f"AMF STATS: input_full={c_input_full.value} retries={c_retries.value} dropped={c_dropped.value} submitted={c_sub.value} received={c_rec.value}", flush=True)
            print(f"Detailed proof JSON: {bp_path}", flush=True)
            print("=" * 95, flush=True)
        except Exception as _bp_exc:
            print(f"[AMD NATIVE] WARNING: failed to compute bottleneck proof: {_bp_exc}", flush=True)

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

    progress_tracker.complete(time.time() - start_time)
    return True
