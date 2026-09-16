"""Canonical payload dump helper for NVIDIA export boundary diagnostics.

Serializes all arguments passed to export_nvidia_native_d3d11 into a stable,
deterministic canonical dictionary and JSON structure without pointer addresses.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional


def hash_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def hash_file(path: Optional[Path | str]) -> Optional[str]:
    if not path:
        return None
    p = Path(path).resolve()
    if not p.is_file():
        return None
    return hash_bytes(p.read_bytes())


def serialize_telemetry_series(samples: Optional[List[Any]]) -> dict[str, Any]:
    if not samples:
        return {"count": 0, "hash": "EMPTY"}
    # Serialize tuples of (timestamp, value) deterministically
    simplified = []
    for item in samples:
        if isinstance(item, (list, tuple)) and len(item) >= 2:
            ts = item[0]
            val = item[1]
            ts_val = ts.timestamp() if hasattr(ts, "timestamp") else float(ts)
            simplified.append((round(ts_val, 4), round(float(val), 4) if val is not None else None))
        elif hasattr(item, "timestamp") and hasattr(item, "value"):
            ts = item.timestamp
            ts_val = ts.timestamp() if hasattr(ts, "timestamp") else float(ts)
            simplified.append((round(ts_val, 4), round(float(item.value), 4) if item.value is not None else None))
    encoded = json.dumps(simplified, sort_keys=True).encode("utf-8")
    return {
        "count": len(samples),
        "hash": hash_bytes(encoded),
    }


def serialize_telemetry(telemetry: Any) -> dict[str, Any]:
    if telemetry is None:
        return {"type": "None", "present": False}

    start_dt = getattr(telemetry, "start_dt_utc", None)
    fit_path = getattr(telemetry, "fit_file_path", None)
    gpmf_path = getattr(telemetry, "gpmf_file_path", None)

    series_info = {
        "speed_samples": serialize_telemetry_series(getattr(telemetry, "speed_samples", None)),
        "heart_rate_samples": serialize_telemetry_series(getattr(telemetry, "heart_rate_samples", None)),
        "cadence_samples": serialize_telemetry_series(getattr(telemetry, "cadence_samples", None)),
        "altitude_samples": serialize_telemetry_series(getattr(telemetry, "altitude_samples", None)),
        "power_samples": serialize_telemetry_series(getattr(telemetry, "power_samples", None)),
        "temperature_samples": serialize_telemetry_series(getattr(telemetry, "temperature_samples", None)),
        "slope_samples": serialize_telemetry_series(getattr(telemetry, "slope_samples", None)),
        "fit_gps_track": serialize_telemetry_series(getattr(telemetry, "fit_gps_track", None)),
    }

    # Combined hash of all series
    combined_hash_str = "|".join(
        f"{k}:{v['count']}:{v['hash']}" for k, v in sorted(series_info.items())
    )

    return {
        "type": type(telemetry).__name__,
        "present": True,
        "start_dt_utc": start_dt.isoformat() if start_dt else None,
        "start_dt_tz": str(getattr(start_dt, "tzinfo", None)),
        "fit_file_path": str(fit_path) if fit_path else None,
        "fit_file_sha256": hash_file(fit_path),
        "gpmf_file_path": str(gpmf_path) if gpmf_path else None,
        "gpmf_file_sha256": hash_file(gpmf_path),
        "series": series_info,
        "combined_telemetry_hash": hash_bytes(combined_hash_str.encode("utf-8")),
    }


def serialize_video_timeline(video_timeline: Any) -> Optional[dict[str, Any]]:
    if video_timeline is None:
        return None

    clip_count = getattr(video_timeline, "clip_count", 0)
    total_duration_s = getattr(video_timeline, "total_duration_s", 0.0)
    total_frames = getattr(video_timeline, "total_frames", 0)
    fps = getattr(video_timeline, "fps", 0.0)

    clips_data = []
    if hasattr(video_timeline, "clips"):
        for clip in video_timeline.clips:
            clips_data.append({
                "path": str(getattr(clip, "path", clip)),
                "duration_s": getattr(clip, "duration_s", None),
                "in_point_s": getattr(clip, "in_point_s", None),
                "out_point_s": getattr(clip, "out_point_s", None),
                "speed": getattr(clip, "speed", 1.0),
            })

    encoded = json.dumps({
        "clip_count": clip_count,
        "total_duration_s": total_duration_s,
        "total_frames": total_frames,
        "fps": fps,
        "clips": clips_data,
    }, sort_keys=True).encode("utf-8")

    return {
        "type": type(video_timeline).__name__,
        "clip_count": clip_count,
        "total_duration_s": total_duration_s,
        "total_frames": total_frames,
        "fps": fps,
        "clips": clips_data,
        "canonical_hash": hash_bytes(encoded),
    }


def serialize_layout(layout: dict) -> dict[str, Any]:
    sorted_json = json.dumps(layout, sort_keys=True)
    in_memory_sha256 = hash_bytes(sorted_json.encode("utf-8"))

    widgets = layout.get("widgets", {}) or layout.get("indicators", {}) or {}
    widget_keys = sorted(widgets.keys())

    widgets_summary = []
    for k in widget_keys:
        w = widgets[k]
        widgets_summary.append({
            "key": k,
            "type": w.get("type"),
            "pos": w.get("pos"),
            "size": w.get("size"),
            "enabled": w.get("enabled", True),
        })

    cut_regions = layout.get("cut_regions")

    return {
        "in_memory_sha256": in_memory_sha256,
        "top_level_keys": sorted(list(layout.keys())),
        "widget_count": len(widget_keys),
        "widget_keys": widget_keys,
        "widgets_summary": widgets_summary,
        "has_cut_regions": "cut_regions" in layout,
        "cut_regions_count": len(cut_regions) if isinstance(cut_regions, list) else (1 if cut_regions else 0),
        "cut_regions": cut_regions,
    }


def dump_canonical_payload(
    *,
    input_files: List[Any],
    output_file: Path | str,
    layout: dict,
    telemetry: Any,
    video_timeline: Optional[Any] = None,
    codec: str = "HEVC",
    quality_profile: str = "Fast",
    video_bitrate: str | float = "40M",
    enable_compression_analysis: bool = False,
    compression_csv_path: Optional[Path | str] = None,
    max_frames: Optional[int] = None,
    start_frame: int = 0,
    enable_preview: bool = False,
    preview_width: int = 960,
    preview_height: int = 540,
    preview_fps: float = 8.0,
    gui_runtime_snapshot: Optional[dict[str, Any]] = None,
    progress_cb: Optional[Any] = None,
    on_render_progress: Optional[Any] = None,
    cancel_event: Optional[Any] = None,
    active_process_holder: Optional[Any] = None,
    on_preview_frame: Optional[Any] = None,
    layout_file_path: Optional[str] = None,
    dll_path: Optional[str] = None,
) -> dict[str, Any]:
    """Serialize all export arguments into a stable canonical JSON-ready dictionary."""
    from src.ffmpeg.nvidia_config import (
        LOCKED_PROFILES,
        get_native_dll_path,
        resolve_nvidia_profile,
    )
    from src.ffmpeg.nvidia_native_exporter import (
        build_canonical_indicators,
        build_map_indicator_desc,
    )
    from src.indicators.frame_data import compute_indicator_auto_ranges

    # Normalize inputs
    resolved_inputs = []
    for item in input_files:
        p = Path(getattr(item, "path", item)).resolve()
        resolved_inputs.append({
            "path": str(p),
            "exists": p.is_file(),
            "size": p.stat().st_size if p.is_file() else None,
            "sha256": hash_file(p),
        })

    resolved_output = str(Path(output_file).resolve())
    resolved_dll = Path(dll_path or get_native_dll_path()).resolve()

    dll_info = {
        "path": str(resolved_dll),
        "exists": resolved_dll.is_file(),
        "size": resolved_dll.stat().st_size if resolved_dll.is_file() else None,
        "mtime": (
            resolved_dll.stat().st_mtime if resolved_dll.is_file() else None
        ),
        "sha256": hash_file(resolved_dll),
    }

    # Profile resolution
    profile_name = resolve_nvidia_profile(codec, quality_profile)
    profile_spec = LOCKED_PROFILES.get(profile_name, {})

    # Layout serialization
    layout_serialized = serialize_layout(layout)
    if layout_file_path:
        lf = Path(layout_file_path).resolve()
        layout_serialized["layout_file_path"] = str(lf)
        layout_serialized["layout_file_sha256"] = hash_file(lf)
    else:
        layout_serialized["layout_file_path"] = None
        layout_serialized["layout_file_sha256"] = None

    # Telemetry serialization
    telemetry_serialized = serialize_telemetry(telemetry)

    # Video timeline serialization
    timeline_serialized = serialize_video_timeline(video_timeline)

    # Derived indicator descriptors
    auto_ranges = compute_indicator_auto_ranges(
        layout,
        speed_samples=getattr(telemetry, "speed_samples", None),
        alt_samples=getattr(telemetry, "alt_samples", None),
        iso_samples=getattr(telemetry, "iso_samples", None),
        exposure_samples=getattr(telemetry, "exposure_samples", None),
        temperature_samples=getattr(telemetry, "temperature_samples", None),
        fit_data=getattr(telemetry, "fit_data", {}),
    )

    indicators_list = build_canonical_indicators(layout, auto_ranges)
    indicators_canonical = []
    for ind in indicators_list:
        key = bytes(ind.key).split(b"\0", 1)[0].decode("utf-8", errors="replace")
        indicators_canonical.append({
            "key": key,
            "type": int(ind.type),
            "x": round(float(ind.x), 2),
            "y": round(float(ind.y), 2),
            "width": round(float(ind.width), 2),
            "height": round(float(ind.height), 2),
            "rotation": round(float(ind.rotation), 2),
            "alpha": round(float(ind.alpha), 2),
            "z_order": int(ind.z_order),
        })
    indicators_hash = hash_bytes(json.dumps(indicators_canonical, sort_keys=True).encode("utf-8"))

    # Map descriptor
    map_desc = build_map_indicator_desc(layout)
    if map_desc:
        map_key = bytes(map_desc.key).split(b"\0", 1)[0].decode("utf-8", errors="replace")
        map_canonical = {
            "key": map_key,
            "type": int(map_desc.type),
            "x": round(float(map_desc.x), 2),
            "y": round(float(map_desc.y), 2),
            "width": round(float(map_desc.width), 2),
            "height": round(float(map_desc.height), 2),
            "rotation": round(float(map_desc.rotation), 2),
            "alpha": round(float(map_desc.alpha), 2),
            "z_order": int(map_desc.z_order),
            "zoom": int(map_desc.style.map.zoom),
            "track_width": round(float(map_desc.style.map.track_width), 2),
            "marker_radius": round(float(map_desc.style.map.marker_radius), 2),
        }
        map_hash = hash_bytes(json.dumps(map_canonical, sort_keys=True).encode("utf-8"))
    else:
        map_canonical = None
        map_hash = "NONE"

    # Overall payload summary
    payload = {
        "dll": dll_info,
        "input_files": resolved_inputs,
        "output_file": resolved_output,
        "layout": layout_serialized,
        "telemetry": telemetry_serialized,
        "video_timeline": timeline_serialized,
        "codec": codec,
        "quality_profile": quality_profile,
        "resolved_profile_name": profile_name,
        "locked_profile_spec": {
            k: v for k, v in profile_spec.items() if isinstance(v, (int, float, str, bool))
        },
        "video_bitrate": str(video_bitrate),
        "enable_compression_analysis": bool(enable_compression_analysis),
        "compression_csv_path": str(compression_csv_path) if compression_csv_path else None,
        "max_frames": max_frames,
        "start_frame": int(start_frame),
        "enable_preview": bool(enable_preview),
        "preview_width": int(preview_width),
        "preview_height": int(preview_height),
        "preview_fps": float(preview_fps),
        "callbacks": {
            "progress_cb": progress_cb is not None,
            "on_render_progress": on_render_progress is not None,
            "cancel_event": cancel_event is not None,
            "active_process_holder": active_process_holder is not None,
            "on_preview_frame": on_preview_frame is not None,
        },
        "derived_native": {
            "indicator_count": len(indicators_canonical),
            "indicator_canonical_hash": indicators_hash,
            "indicators": indicators_canonical,
            "map_descriptor_present": map_canonical is not None,
            "map_descriptor_hash": map_hash,
            "map_descriptor": map_canonical,
        },
        "gui_runtime_snapshot": gui_runtime_snapshot,
    }

    return payload
