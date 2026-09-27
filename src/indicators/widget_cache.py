"""Generic per-widget CPU render cache for TeleM overlay indicators.

Provides deterministic, layout-safe, data-source-independent caching based on
canonical visual signatures (pixel-determining state).
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Optional

try:
    from PIL import Image
except ImportError:
    Image = None  # type: ignore


def _freeze_val(v: Any) -> Any:
    """Recursively convert unhashable objects into immutable, hashable structures."""
    if isinstance(v, (str, int, float, bool, type(None), bytes)):
        return v
    if isinstance(v, (list, tuple)):
        return tuple(_freeze_val(x) for x in v)
    if isinstance(v, dict):
        return tuple(sorted((str(k), _freeze_val(val)) for k, val in v.items() if not str(k).startswith("_")))
    return str(v)


def compute_segment_bar_visual_signature(
    value: Any,
    formatted_val: Optional[str],
    unit: str,
    label: str,
    cfg: Mapping[str, Any],
    val_min: float,
    val_max: float,
    size_px: int,
    fs: int,
    outline: int,
    ss: int,
    canvas_w: int,
    canvas_h: int,
    font_path: str,
    key: Optional[str] = None,
) -> tuple:
    """Compute canonical visual state for segment_bar renderer.

    Includes only inputs that determine output pixels:
    - value_text (rendered string)
    - active (integer count of active segments)
    - partial_state (partial segment info if fill_mode == 'partial')
    - marker_x (discrete marker pixel position if marker enabled)
    - complete layout / style geometry & colors (cfg_frozen)
    """
    key_str = str(key or "").lower()
    label_str = str(label or "").lower()
    field_str = str(cfg.get("field", "")).lower()
    is_solar = "solar" in key_str or "solar" in label_str or "solar" in field_str
    is_pct = is_solar or unit == "%" or "battery" in key_str or "battery" in label_str or "battery" in field_str

    val_min_f = float(val_min)
    val_max_f = float(val_max)
    range_span = val_max_f - val_min_f if val_max_f != val_min_f else 1.0

    if value is not None:
        raw_val = float(value)
        normalized_fraction = max(0.0, min(1.0, (raw_val - val_min_f) / range_span))
        if is_solar:
            display_value = raw_val
        elif is_pct:
            display_value = normalized_fraction * 100.0
        else:
            display_value = raw_val
    else:
        raw_val = 0.0
        normalized_fraction = 0.0
        display_value = None

    # Value text as rendered
    show_value = bool(cfg.get("show_value", True))
    unit_for_value = str(cfg.get("value_unit", unit or ""))
    if not show_value:
        value_text = ""
    elif formatted_val is not None:
        if not bool(cfg.get("value_show_unit", True)):
            val_stripped = str(formatted_val)
            for u in (unit_for_value, str(unit or "")):
                if u and val_stripped.endswith(u):
                    val_stripped = val_stripped[:-len(u)].strip()
            value_text = val_stripped
        elif str(cfg.get("value_unit", "")) != "":
            custom_u = str(cfg["value_unit"])
            orig_u = str(unit or "")
            val_str = str(formatted_val)
            if orig_u and val_str.endswith(orig_u):
                value_text = f"{val_str[:-len(orig_u)].strip()} {custom_u}"
            else:
                value_text = f"{val_str} {custom_u}"
        else:
            value_text = str(formatted_val)
    elif display_value is not None:
        decimals = max(0, int(cfg.get("decimals", 0 if is_pct else 1)))
        num_str = f"{float(display_value):.{decimals}f}"
        if bool(cfg.get("value_show_unit", True)) and unit_for_value:
            value_text = f"{num_str} {unit_for_value}"
        else:
            value_text = num_str
    else:
        value_text = "--"

    # Active segments & partial fraction
    segments = max(1, int(cfg.get("segments", cfg.get("segment_count", 30))))
    fill_mode = str(cfg.get("segment_fill_mode", "whole")).strip().lower()
    if fill_mode not in ("whole", "partial"):
        fill_mode = "whole"

    if display_value is not None:
        frac = 0.0 if val_max_f <= val_min_f else max(0.0, min(1.0, (float(display_value) - val_min_f) / range_span))
        if fill_mode == "partial" and 0.0 < frac < 1.0:
            scaled = frac * segments
            active = min(segments, int(math.floor(scaled)))
            partial_frac = max(0.0, min(1.0, scaled - active))
        else:
            active = 0 if frac <= 0.0 else min(segments, int(math.ceil(frac * segments - 1e-12)))
            partial_frac = 0.0
    else:
        active = 0
        partial_frac = 0.0
        frac = 0.0

    partial_state = (active, round(partial_frac, 4)) if (partial_frac > 0.0 and active > 0) else None

    # Marker position (only if marker enabled)
    marker_style = str(cfg.get("marker_style", "none")).strip().lower()
    marker_enabled = (marker_style != "none") and bool(cfg.get("show_marker", True))
    if marker_enabled and display_value is not None:
        ss_int = max(1, int(ss))
        width = max(80 * ss_int, int(size_px * ss_int))
        marker_x = int(round(frac * width))
    else:
        marker_x = None

    cfg_frozen = _freeze_val(cfg)

    return (
        "segment_bar",
        value_text,
        active,
        partial_state,
        marker_x,
        str(unit or ""),
        str(label or ""),
        val_min_f,
        val_max_f,
        int(size_px),
        int(fs),
        int(outline),
        int(ss),
        int(canvas_w),
        int(canvas_h),
        str(font_path or ""),
        cfg_frozen,
    )


def compute_visual_signature(
    renderer_type: str,
    value: Any,
    formatted_val: Optional[str],
    unit: str,
    label: str,
    cfg: Mapping[str, Any],
    val_min: float,
    val_max: float,
    size_px: int,
    fs: int,
    outline: int,
    ss: int,
    canvas_w: int,
    canvas_h: int,
    font_path: str,
    key: Optional[str] = None,
) -> tuple:
    """Compute a complete, deterministic visual signature for an indicator render.
    
    For segment_bar: uses canonical visual state (value_text, active segments, partial, marker).
    For other renderers: uses generic state representation.
    """
    if renderer_type in ("segment_bar", "segments"):
        return compute_segment_bar_visual_signature(
            value=value,
            formatted_val=formatted_val,
            unit=unit,
            label=label,
            cfg=cfg,
            val_min=val_min,
            val_max=val_max,
            size_px=size_px,
            fs=fs,
            outline=outline,
            ss=ss,
            canvas_w=canvas_w,
            canvas_h=canvas_h,
            font_path=font_path,
            key=key,
        )

    cfg_frozen = _freeze_val(cfg)
    v_repr = float(value) if value is not None else None
    return (
        renderer_type,
        v_repr,
        str(formatted_val) if formatted_val is not None else None,
        str(unit or ""),
        str(label or ""),
        float(val_min),
        float(val_max),
        int(size_px),
        int(fs),
        int(outline),
        int(ss),
        int(canvas_w),
        int(canvas_h),
        str(font_path or ""),
        cfg_frozen,
    )


@dataclass
class WidgetInstanceStats:
    renderer_type: str
    hits: int = 0
    misses: int = 0
    lookup_ns_total: int = 0
    render_ns_total: int = 0
    raw_value_changes: int = 0
    visual_state_changes: int = 0

    @property
    def total_requests(self) -> int:
        return self.hits + self.misses

    @property
    def hit_ratio(self) -> float:
        return (self.hits / self.total_requests) if self.total_requests > 0 else 0.0

    @property
    def lookup_avg_ms(self) -> float:
        return (self.lookup_ns_total / max(1, self.total_requests)) / 1_000_000.0

    @property
    def render_avg_ms(self) -> float:
        return (self.render_ns_total / max(1, self.misses)) / 1_000_000.0 if self.misses > 0 else 0.0


class WidgetInstanceCache:
    def __init__(self, renderer_type: str):
        self.renderer_type = renderer_type
        self.last_signature: Optional[tuple] = None
        self.last_result: Optional[tuple[Optional[Image.Image], int, int, Optional[dict[str, Any]]]] = None
        self.last_raw_value: Any = None
        self.has_seen_raw_value: bool = False
        self.stats = WidgetInstanceStats(renderer_type=renderer_type)


class WidgetRenderCache:
    """Per-session generic widget render cache."""

    def __init__(self, enabled: bool = False):
        self.enabled = enabled
        self.instances: dict[str, WidgetInstanceCache] = {}
        # Initial supported renderer types
        self.supported_renderers = {"segment_bar", "segments"}

    def clear(self) -> None:
        self.instances.clear()

    def get_or_render(
        self,
        instance_key: str,
        renderer_type: str,
        compute_sig_fn: Callable[[], tuple],
        render_fn: Callable[[], tuple[Optional[Image.Image], int, int, Optional[dict[str, Any]]]],
        raw_value: Any = None,
    ) -> tuple[Optional[Image.Image], int, int, Optional[dict[str, Any]]]:
        """Look up cached raster by signature or render and store if missing/changed."""
        if not self.enabled or renderer_type not in self.supported_renderers:
            return render_fn()

        t_look0 = time.perf_counter_ns()
        sig = compute_sig_fn()
        inst = self.instances.get(instance_key)
        if inst is None:
            inst = WidgetInstanceCache(renderer_type=renderer_type)
            self.instances[instance_key] = inst

        # Track raw value changes
        if not inst.has_seen_raw_value:
            inst.has_seen_raw_value = True
            inst.last_raw_value = raw_value
            inst.stats.raw_value_changes += 1
        elif raw_value != inst.last_raw_value:
            inst.stats.raw_value_changes += 1
            inst.last_raw_value = raw_value

        if inst.last_signature is not None and inst.last_signature == sig and inst.last_result is not None:
            inst.stats.hits += 1
            inst.stats.lookup_ns_total += time.perf_counter_ns() - t_look0
            return inst.last_result

        # Cache Miss (visual state changed or first render)
        inst.stats.misses += 1
        inst.stats.visual_state_changes += 1
        inst.stats.lookup_ns_total += time.perf_counter_ns() - t_look0

        t_rend0 = time.perf_counter_ns()
        result = render_fn()
        inst.stats.render_ns_total += time.perf_counter_ns() - t_rend0

        inst.last_signature = sig
        inst.last_result = result
        return result

    def get_stats(self) -> dict[str, Any]:
        total_hits = sum(i.stats.hits for i in self.instances.values())
        total_misses = sum(i.stats.misses for i in self.instances.values())
        total_raw_changes = sum(i.stats.raw_value_changes for i in self.instances.values())
        total_visual_changes = sum(i.stats.visual_state_changes for i in self.instances.values())
        total_reqs = total_hits + total_misses
        hit_ratio = (total_hits / total_reqs) if total_reqs > 0 else 0.0
        return {
            "enabled": self.enabled,
            "total_hits": total_hits,
            "total_misses": total_misses,
            "total_hit_ratio": hit_ratio,
            "total_raw_value_changes": total_raw_changes,
            "total_visual_state_changes": total_visual_changes,
            "instances": {
                k: {
                    "renderer_type": inst.stats.renderer_type,
                    "hits": inst.stats.hits,
                    "misses": inst.stats.misses,
                    "hit_ratio": inst.stats.hit_ratio,
                    "lookup_avg_ms": inst.stats.lookup_avg_ms,
                    "render_avg_ms": inst.stats.render_avg_ms,
                    "raw_value_changes": inst.stats.raw_value_changes,
                    "visual_state_changes": inst.stats.visual_state_changes,
                }
                for k, inst in self.instances.items()
            },
        }


# Global / session singleton getter
_CURRENT_CACHE: Optional[WidgetRenderCache] = None


def get_widget_cache(enabled: Optional[bool] = None) -> WidgetRenderCache:
    global _CURRENT_CACHE
    if _CURRENT_CACHE is None:
        _CURRENT_CACHE = WidgetRenderCache(enabled=enabled if enabled is not None else False)
    elif enabled is not None:
        _CURRENT_CACHE.enabled = enabled
    return _CURRENT_CACHE


def reset_widget_cache(enabled: Optional[bool] = None) -> WidgetRenderCache:
    global _CURRENT_CACHE
    _CURRENT_CACHE = WidgetRenderCache(enabled=enabled if enabled is not None else False)
    return _CURRENT_CACHE
