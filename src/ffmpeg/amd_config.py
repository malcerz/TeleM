"""Shared AMD production/benchmark configuration governance.

This module deliberately contains only configuration resolution.  It does not
change the GUI's environment semantics; the canonical benchmark runner can
explicitly clear ambient overrides before calling the normal exporter.
"""

from __future__ import annotations

import hashlib
import json
import os
from typing import Mapping


PRODUCTION_DEFAULTS = {
    "pipeline": "SYNC",
    "queue_depth": 0,
    "vp_state": "REFERENCE",
    "vp_cache_frame_format": 0,
    "vp_cache_source_rect": 0,
    "vp_cache_dest_rect": 0,
    "vp_setter_order": "FORMAT_SRC_DST",
    "vp_completion_probe": 0,
    "vp_processor_ring": 1,
    "base_convert": "VP_REFERENCE",
    "common_text_fast": 0,
    "vp_pool": "8",
    "amf_query": "REFERENCE",
    "map": "GPU",
    "chart": "GPU_SPLIT",
    "gauge": "GPU",
    "lean": 1,
    "hud": "GPU_HUD",
    "hud_upload": "DIRTY",
    "nv12": "FUSED",
    "above_batched": 0,
    "above_dirty": "EXACT",
    "above_upload": "DIRECT",
    "above_fine_dirty": 0,
    "above_sparse": 0,
    "above_multi_rect": 1,
    "hud_buffer": "REFERENCE",
}

GOVERNED_AMD_ENV = (
    "AMD_CPU_GPU_PIPELINE",
    "AMD_QUEUE_DEPTH",
    "AMD_VP_STATE_MODE",
    "AMD_VP_CACHE_FRAME_FORMAT",
    "AMD_VP_CACHE_SOURCE_RECT",
    "AMD_VP_CACHE_DEST_RECT",
    "AMD_VP_SETTER_ORDER",
    "AMD_VP_COMPLETION_PROBE",
    "AMD_VP_PROCESSOR_RING_SIZE",
    "AMD_BASE_CONVERT_MODE",
    "AMD_ABOVE_COMMON_TEXT_FAST",
    "AMD_VP_POOL_SIZE",
    "AMD_AMF_QUERY_MODE",
    "AMD_MAP_PATH",
    "AMD_CHART_PATH",
    "AMD_AFTER_MAP_CHART_GPU",
    "AMD_AFTER_MAP_GAUGE_GPU",
    "AMD_GAUGE_PATH",
    "AMD_LEAN_GPU",
    "AMD_NATIVE_HUD_MODE",
    "AMD_NATIVE_HUD_UPLOAD_MODE",
    "AMD_NV12_COMPOSITOR",
    "AMD_FUSED_COMPOSITOR",
    "AMD_ABOVE_BATCHED",
    "AMD_ABOVE_DIRTY_MODE",
    "AMD_ABOVE_FINE_DIRTY",
    "AMD_ABOVE_SPARSE_COMPOSE",
    "AMD_ABOVE_UPLOAD_BUFFER_MODE",
    "AMD_ABOVE_MULTI_RECT",
    "AMD_HUD_BUFFER_MODE",
)


def _truthy(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _ignored_overrides(env: Mapping[str, str]) -> dict[str, str]:
    raw = env.get("AMD_BENCHMARK_IGNORED_OVERRIDES", "")
    if not raw:
        return {}
    try:
        value = json.loads(raw)
    except (TypeError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def resolve_amd_config(env: Mapping[str, str] | None = None) -> dict:
    """Resolve the effective AMD production-facing configuration."""
    values = os.environ if env is None else env
    pipeline = values.get("AMD_CPU_GPU_PIPELINE", "SYNC").strip().upper()
    if pipeline not in {"SYNC", "ASYNC"}:
        pipeline = "SYNC"
    if pipeline == "ASYNC":
        try:
            queue_depth = max(1, int(values.get("AMD_QUEUE_DEPTH", "2")))
        except (TypeError, ValueError):
            queue_depth = 2
    else:
        queue_depth = 0

    vp_state = values.get("AMD_VP_STATE_MODE", "REFERENCE").strip().upper()
    if vp_state not in {"REFERENCE", "STATIC_CACHE", "REORDER"}:
        vp_state = "REFERENCE"
    amf_query = values.get("AMD_AMF_QUERY_MODE", "REFERENCE").strip().upper()
    if amf_query not in {"REFERENCE", "DRAIN_READY"}:
        amf_query = "REFERENCE"
    vp_pool = values.get("AMD_VP_POOL_SIZE", "8").strip() or "8"
    base_convert = values.get("AMD_BASE_CONVERT_MODE", "VP_REFERENCE").strip().upper()
    if base_convert not in {"VP_REFERENCE", "COMPUTE_P010_NV12"}:
        base_convert = "VP_REFERENCE"
    common_text_fast = int(_truthy(values.get("AMD_ABOVE_COMMON_TEXT_FAST"), False))
    vp_setter_order = values.get("AMD_VP_SETTER_ORDER", "FORMAT_SRC_DST").strip().upper()
    if vp_setter_order not in {"FORMAT_SRC_DST", "SRC_FORMAT_DST", "DST_SRC_FORMAT"}:
        vp_setter_order = "FORMAT_SRC_DST"
    map_path = values.get("AMD_MAP_PATH", "GPU").strip().upper()
    if map_path not in {"GPU", "CPU_REFERENCE"}:
        map_path = "GPU"
    chart = values.get("AMD_CHART_PATH", "GPU_SPLIT").strip().upper()
    if not _truthy(values.get("AMD_AFTER_MAP_CHART_GPU"), True):
        chart = "CPU_REFERENCE"
    if chart not in {"CPU_REFERENCE", "GPU", "GPU_SPLIT"}:
        chart = "GPU_SPLIT"
    gauge = values.get("AMD_GAUGE_PATH", "GPU").strip().upper()
    if not _truthy(values.get("AMD_AFTER_MAP_GAUGE_GPU"), True):
        gauge = "CPU_REFERENCE"
    if gauge not in {"CPU_REFERENCE", "GPU"}:
        gauge = "GPU"
    hud = values.get("AMD_NATIVE_HUD_MODE", "GPU_HUD").strip().upper()
    if hud not in {"GPU_HUD", "CPU_REFERENCE"}:
        hud = "GPU_HUD"
    hud_upload = values.get("AMD_NATIVE_HUD_UPLOAD_MODE", "DIRTY").strip().upper()
    if hud_upload not in {"FULL", "DIRTY"}:
        hud_upload = "DIRTY"
    nv12 = "FUSED" if values.get("AMD_FUSED_COMPOSITOR", "1").strip() == "1" else "LEGACY_SEPARATE"
    above_dirty = values.get("AMD_ABOVE_DIRTY_MODE", "EXACT").strip().upper()
    if above_dirty not in {"SCAN", "CANDIDATE", "EXACT"}:
        above_dirty = "SCAN"
    above_upload = values.get("AMD_ABOVE_UPLOAD_BUFFER_MODE", "DIRECT").strip().upper()
    if above_upload not in {"COPY", "DIRECT"}:
        above_upload = "COPY"
    hud_buffer = values.get("AMD_HUD_BUFFER_MODE", "REFERENCE").strip().upper()
    if hud_buffer not in {"REFERENCE", "OPTIMIZED"}:
        hud_buffer = "REFERENCE"
    return {
        "pipeline": pipeline,
        "queue_depth": queue_depth,
        "vp_state": vp_state,
        "vp_cache_frame_format": int(_truthy(values.get("AMD_VP_CACHE_FRAME_FORMAT"), False)),
        "vp_cache_source_rect": int(_truthy(values.get("AMD_VP_CACHE_SOURCE_RECT"), False)),
        "vp_cache_dest_rect": int(_truthy(values.get("AMD_VP_CACHE_DEST_RECT"), False)),
        "vp_setter_order": vp_setter_order,
        "vp_completion_probe": int(_truthy(values.get("AMD_VP_COMPLETION_PROBE"), False)),
        "vp_processor_ring": max(1, min(3, int(values.get("AMD_VP_PROCESSOR_RING_SIZE", "1"))))
        if str(values.get("AMD_VP_PROCESSOR_RING_SIZE", "1")).isdigit() else 1,
        "base_convert": base_convert,
        "common_text_fast": common_text_fast,
        "vp_pool": vp_pool,
        "amf_query": amf_query,
        "map": map_path,
        "chart": chart,
        "gauge": gauge,
        "lean": int(_truthy(values.get("AMD_LEAN_GPU"), True)),
        "hud": hud,
        "hud_upload": hud_upload,
        "nv12": nv12,
        "above_batched": int(_truthy(values.get("AMD_ABOVE_BATCHED"), False)),
        "above_dirty": above_dirty,
        "above_upload": above_upload,
        "above_fine_dirty": int(_truthy(values.get("AMD_ABOVE_FINE_DIRTY"), False)),
        "above_sparse": int(_truthy(values.get("AMD_ABOVE_SPARSE_COMPOSE"), False)),
        "above_multi_rect": int(_truthy(values.get("AMD_ABOVE_MULTI_RECT"), True)),
        "hud_buffer": hud_buffer,
        "benchmark_mode": values.get("AMD_BENCHMARK_MODE", "DIRECT_RUNTIME"),
        "active_env_overrides": {
            key: values[key] for key in GOVERNED_AMD_ENV if key in values
        },
        "ignored_env_overrides": _ignored_overrides(values),
    }


def make_benchmark_fingerprint(
    config: dict,
    *,
    video: str | None = None,
    fit: str | None = None,
    layout: str | None = None,
    layout_sha256: str | None = None,
    output: str | None = None,
) -> str:
    payload = {
        "benchmark_mode": config.get("benchmark_mode"),
        "video": video,
        "fit": fit,
        "layout": layout,
        "layout_sha256": layout_sha256,
        "config": {key: config.get(key) for key in PRODUCTION_DEFAULTS},
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def clear_ambient_overrides(env: dict[str, str]) -> dict[str, str]:
    """Remove governed AMD overrides and return the removed key/value pairs."""
    removed = {key: env[key] for key in GOVERNED_AMD_ENV if key in env}
    for key in removed:
        env.pop(key, None)
    return removed
