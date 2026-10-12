"""Shared alpha-based outline and distance-faded shadow for HUD rasters.

Accelerated via vectorized OpenCV morphological dilation and NumPy array slicing.
Supports both modern 0–100% scale (effects_version: 2) and legacy 540p logical px.
Padding preserves the widget centre; original raster composited on top.
"""
from __future__ import annotations

import math
import os
import time
from collections import defaultdict
from hashlib import blake2b
from typing import Any
import numpy as np
import cv2
from PIL import Image

from src.indicators.helpers import _BoundedStaticCache, parse_hex_color

_EFFECT_CACHE = _BoundedStaticCache(max_entries=1024)
_LUT_CACHE: dict[float, np.ndarray] = {}
_PROFILE_EFFECT_CACHE = os.environ.get("TELEM_EFFECTS_CACHE_PROFILE", "0").strip().lower() in {"1", "true", "yes", "on"}
_EFFECT_PROFILE: dict[str, dict[str, float]] = defaultdict(dict)


def _profile_add(key: str, field: str, value: float = 1.0) -> None:
    if not _PROFILE_EFFECT_CACHE:
        return
    row = _EFFECT_PROFILE.setdefault(key, {})
    row[field] = row.get(field, 0.0) + float(value)


_CACHED_BYTES: int = 0


def clear_effects_cache() -> None:
    """Clear all cached effect rasters."""
    global _CACHED_BYTES
    _EFFECT_CACHE.clear()
    _CACHED_BYTES = 0


def get_effects_cache_stats() -> dict[str, Any]:
    """Return cache statistics for diagnostics."""
    stats: dict[str, Any] = _EFFECT_CACHE.stats()
    stats["cached_rgba_bytes_estimate"] = _CACHED_BYTES
    stats["profile_enabled"] = _PROFILE_EFFECT_CACHE
    if _PROFILE_EFFECT_CACHE:
        stats["profile_by_widget"] = {key: dict(value) for key, value in _EFFECT_PROFILE.items()}
    return stats


def effects_enabled(cfg: dict[str, Any] | None) -> bool:
    """Return True if either outline or shadow is enabled in cfg."""
    if not cfg:
        return False
    return bool(cfg.get("outline_enabled", False) or cfg.get("shadow_enabled", False))


def is_effects_v2(cfg: dict[str, Any]) -> bool:
    """Check if configuration uses modern 0-100% effect parameters (version 2)."""
    if "effects_version" in cfg:
        try:
            return int(cfg["effects_version"]) >= 2
        except (ValueError, TypeError):
            pass
    for k in ("outline_opacity", "shadow_opacity", "outline_fade", "shadow_fade"):
        val = cfg.get(k)
        if val is not None:
            try:
                if float(val) > 1.0:
                    return True
            except (ValueError, TypeError):
                pass
    return False


def migrate_indicator_effects(cfg: dict[str, Any], nominal_dim: float | None = None) -> dict[str, Any]:
    """Migrate an indicator's effect configuration in-place to version 2 (0-100% scale)."""
    if is_effects_v2(cfg):
        cfg["effects_version"] = 2
        return cfg

    # Convert opacity and fade from 0..1 to 0..100%
    for k in ("outline_opacity", "shadow_opacity", "outline_fade", "shadow_fade"):
        if k in cfg and cfg[k] is not None:
            try:
                val = float(cfg[k])
                if val <= 1.0:
                    cfg[k] = round(val * 100.0, 1)
            except (ValueError, TypeError):
                pass

    # Convert geometric px at 540p to percentage of nominal indicator dimension
    ref = float(nominal_dim) if nominal_dim and nominal_dim > 0 else 100.0
    for k in ("outline_width", "shadow_distance", "shadow_length"):
        if k in cfg and cfg[k] is not None:
            try:
                px_val = float(cfg[k])
                # Scale relative to nominal reference dimension
                cfg[k] = round((px_val / ref) * 100.0, 1)
            except (ValueError, TypeError):
                pass

    cfg["effects_version"] = 2
    return cfg


def _get_lut(factor: float) -> np.ndarray:
    key = round(float(factor), 6)
    lut = _LUT_CACHE.get(key)
    if lut is None:
        lut = np.array([round(i * key) for i in range(256)], dtype=np.uint8)
        if len(_LUT_CACHE) > 512:
            _LUT_CACHE.clear()
        _LUT_CACHE[key] = lut
    return lut


def apply_indicator_effects(
    image: Image.Image | None,
    cfg: dict[str, Any] | None,
    min_dim: int,
    *,
    profile_key: str | None = None,
    breakdown: Optional[dict[str, float]] = None,
) -> Image.Image | None:
    """Apply alpha-based outline and distance-faded shadow to an indicator raster."""
    if image is None or not effects_enabled(cfg):
        return image

    shadow_enabled = bool(cfg.get("shadow_enabled", False))
    outline_enabled = bool(cfg.get("outline_enabled", False))
    if not shadow_enabled and not outline_enabled:
        return image

    version_2 = is_effects_v2(cfg)
    ref_dim = max(1.0, float(min(image.width, image.height)))

    if version_2:
        out_pct = max(0.0, min(100.0, float(cfg.get("outline_width", 2.0))))
        width = max(0, round((out_pct / 100.0) * ref_dim)) if outline_enabled else 0
        dist_pct = max(0.0, min(100.0, float(cfg.get("shadow_distance", 3.0))))
        distance = max(0.0, (dist_pct / 100.0) * ref_dim) if shadow_enabled else 0.0
        len_pct = max(0.0, min(100.0, float(cfg.get("shadow_length", 0.0))))
        length = max(0.0, (len_pct / 100.0) * ref_dim) if shadow_enabled else 0.0

        out_opacity = max(0.0, min(1.0, float(cfg.get("outline_opacity", 100.0)) / 100.0))
        out_fade = max(0.0, min(1.0, float(cfg.get("outline_fade", 0.0)) / 100.0))
        shad_opacity = max(0.0, min(1.0, float(cfg.get("shadow_opacity", 70.0)) / 100.0))
        shad_fade = max(0.0, min(1.0, float(cfg.get("shadow_fade", 100.0)) / 100.0))
    else:
        # Legacy version 1: distances are logical px at 960x540
        scale = min_dim / 540.0
        width = max(0, round(float(cfg.get("outline_width", 2.0)) * scale)) if outline_enabled else 0
        distance = max(0.0, float(cfg.get("shadow_distance", 3.0)) * scale) if shadow_enabled else 0.0
        length = max(0.0, float(cfg.get("shadow_length", 0.0)) * scale) if shadow_enabled else 0.0

        out_op_raw = float(cfg.get("outline_opacity", 1.0))
        if out_op_raw > 1.0:
            out_op_raw /= 100.0
        out_opacity = max(0.0, min(1.0, out_op_raw))

        out_fade_raw = float(cfg.get("outline_fade", 0.0))
        if out_fade_raw > 1.0:
            out_fade_raw /= 100.0
        out_fade = max(0.0, min(1.0, out_fade_raw))

        shad_op_raw = float(cfg.get("shadow_opacity", 0.7))
        if shad_op_raw > 1.0:
            shad_op_raw /= 100.0
        shad_opacity = max(0.0, min(1.0, shad_op_raw))

        shad_fade_raw = float(cfg.get("shadow_fade", 1.0))
        if shad_fade_raw > 1.0:
            shad_fade_raw /= 100.0
        shad_fade = max(0.0, min(1.0, shad_fade_raw))

    if width == 0 and (not shadow_enabled or (distance == 0.0 and length == 0.0)):
        return image

    shadow_angle = float(cfg.get("shadow_angle", 45.0))
    outline_color = parse_hex_color(cfg.get("outline_color", "#000000")) or (0, 0, 0)
    shadow_color = parse_hex_color(cfg.get("shadow_color", "#000000")) or (0, 0, 0)

    # Cache only the effect layers by alpha content. Object IDs can be reused
    # and images can be mutated in place, so validate the alpha every time.
    # RGB is deliberately not part of the cached layer: it is composited from
    # the current image below, which keeps dynamic values/colors fresh.
    cfg_sig = (
        outline_enabled, outline_color[:3], width, out_opacity, out_fade,
        shadow_enabled, shadow_color[:3], round(distance, 2), round(length, 2),
        shadow_angle, shad_opacity, shad_fade,
    )
    widget_key = profile_key or "unattributed"
    profile_start_ns = time.perf_counter_ns() if _PROFILE_EFFECT_CACHE else 0

    dynamic_key = getattr(image, "_dynamic_key", None)
    if dynamic_key is not None:
        full_dyn_key = ("effects_full_dyn", dynamic_key, image.size, cfg_sig)
        cached_full = _EFFECT_CACHE.get(full_dyn_key)
        if cached_full is not None:
            if breakdown is not None and profile_key:
                breakdown[f"{profile_key}.shadow"] = 0.0
                breakdown[f"{profile_key}.outline"] = 0.0
                breakdown[f"{profile_key}.lookup"] = 0.0
            return cached_full
        cache_key = (dynamic_key, image.size, cfg_sig)
        use_sub = False
        bx0 = by0 = 0
        sub_w, sub_h = image.size

    alpha_start_ns = time.perf_counter_ns() if _PROFILE_EFFECT_CACHE else 0
    src_alpha = np.array(image.getchannel("A"), dtype=np.uint8)
    if _PROFILE_EFFECT_CACHE:
        _profile_add(widget_key, "calls")
        _profile_add(
            widget_key,
            "alpha_extract_and_convert_ms",
            (time.perf_counter_ns() - alpha_start_ns) / 1_000_000.0,
        )
        _profile_add(widget_key, "alpha_input_bytes", src_alpha.nbytes)
    alpha_scan_start_ns = time.perf_counter_ns() if _PROFILE_EFFECT_CACHE else 0
    if not np.any(src_alpha):
        if _PROFILE_EFFECT_CACHE:
            _profile_add(widget_key, "alpha_scan_ms", (time.perf_counter_ns() - alpha_scan_start_ns) / 1_000_000.0)
            _profile_add(widget_key, "empty_alpha_returns")
            _profile_add(widget_key, "total_ms", (time.perf_counter_ns() - profile_start_ns) / 1_000_000.0)
        return image
    if _PROFILE_EFFECT_CACHE:
        _profile_add(widget_key, "alpha_scan_ms", (time.perf_counter_ns() - alpha_scan_start_ns) / 1_000_000.0)

    bbox = image.getchannel("A").getbbox()
    if bbox is None:
        if _PROFILE_EFFECT_CACHE:
            _profile_add(widget_key, "empty_alpha_returns")
            _profile_add(widget_key, "total_ms", (time.perf_counter_ns() - profile_start_ns) / 1_000_000.0)
        return image

    if dynamic_key is None:
        bx0, by0, bx1, by1 = bbox
        sub_w = bx1 - bx0
        sub_h = by1 - by0
        use_sub = (sub_w * sub_h < image.width * image.height * 0.90)

        if use_sub:
            sub_alpha = src_alpha[by0:by1, bx0:bx1]
            bbox_tag = (bx0, by0, bx1, by1)
            if _PROFILE_EFFECT_CACHE:
                payload_start_ns = time.perf_counter_ns()
                hash_payload = sub_alpha.tobytes()
                _profile_add(widget_key, "alpha_tobytes_ms", (time.perf_counter_ns() - payload_start_ns) / 1_000_000.0)
                hash_start_ns = time.perf_counter_ns()
                content_hash = blake2b(hash_payload, digest_size=16).digest()
                _profile_add(widget_key, "blake2b_ms", (time.perf_counter_ns() - hash_start_ns) / 1_000_000.0)
                _profile_add(widget_key, "hash_input_bytes", len(hash_payload))
                del hash_payload
            else:
                content_hash = blake2b(sub_alpha.tobytes(), digest_size=16).digest()
            cache_key = (content_hash, bbox_tag, image.size, cfg_sig)
        else:
            if _PROFILE_EFFECT_CACHE:
                payload_start_ns = time.perf_counter_ns()
                hash_payload = src_alpha.tobytes()
                _profile_add(widget_key, "alpha_tobytes_ms", (time.perf_counter_ns() - payload_start_ns) / 1_000_000.0)
                hash_start_ns = time.perf_counter_ns()
                content_hash = blake2b(hash_payload, digest_size=16).digest()
                _profile_add(widget_key, "blake2b_ms", (time.perf_counter_ns() - hash_start_ns) / 1_000_000.0)
                _profile_add(widget_key, "hash_input_bytes", len(hash_payload))
                del hash_payload
            else:
                content_hash = blake2b(src_alpha.tobytes(), digest_size=16).digest()
            cache_key = (content_hash, image.size, cfg_sig)

    lookup_start_ns = time.perf_counter_ns() if (_PROFILE_EFFECT_CACHE or breakdown is not None) else 0
    cached = _EFFECT_CACHE.get(cache_key)
    if breakdown is not None and profile_key:
        breakdown[f"{profile_key}.lookup"] = (time.perf_counter_ns() - lookup_start_ns) / 1_000_000.0
    if _PROFILE_EFFECT_CACHE:
        _profile_add(widget_key, "cache_lookup_ms", (time.perf_counter_ns() - lookup_start_ns) / 1_000_000.0)
    if cached is not None:
        effect_layer, pad = cached
        if breakdown is not None and profile_key:
            breakdown[f"{profile_key}.shadow"] = 0.0
            breakdown[f"{profile_key}.outline"] = 0.0
        copy_start_ns = time.perf_counter_ns() if _PROFILE_EFFECT_CACHE else 0
        result = effect_layer.copy()
        if _PROFILE_EFFECT_CACHE:
            _profile_add(widget_key, "cache_hits")
            _profile_add(widget_key, "rgba_allocation_bytes_estimate", effect_layer.width * effect_layer.height * 4)
            _profile_add(widget_key, "cached_layer_copy_ms", (time.perf_counter_ns() - copy_start_ns) / 1_000_000.0)
        composite_start_ns = time.perf_counter_ns() if _PROFILE_EFFECT_CACHE else 0
        result.alpha_composite(image, (pad, pad))
        if _PROFILE_EFFECT_CACHE:
            _profile_add(
                widget_key,
                "current_rgb_composite_ms",
                (time.perf_counter_ns() - composite_start_ns) / 1_000_000.0,
            )
            _profile_add(widget_key, "total_ms", (time.perf_counter_ns() - profile_start_ns) / 1_000_000.0)
        return result

    if _PROFILE_EFFECT_CACHE:
        _profile_add(widget_key, "cache_misses")
    miss_start_ns = time.perf_counter_ns() if (_PROFILE_EFFECT_CACHE or breakdown is not None) else 0

    # Compute bounds and padding
    raw_pad = max(width, (distance + length) if shadow_enabled else 0.0)
    pad = int(math.ceil(raw_pad)) + 2
    W = image.width + 2 * pad
    H = image.height + 2 * pad
    size = (W, H)

    if use_sub:
        mask_W = sub_w + 2 * pad
        mask_H = sub_h + 2 * pad
        mask_size = (mask_W, mask_H)
        mask = np.zeros((mask_H, mask_W), dtype=np.uint8)
        mask[pad:pad + sub_h, pad:pad + sub_w] = sub_alpha
    else:
        mask_W = W
        mask_H = H
        mask_size = size
        mask = np.zeros((H, W), dtype=np.uint8)
        mask[pad:pad + image.height, pad:pad + image.width] = src_alpha

    target_res = None
    has_layer = False

    if _PROFILE_EFFECT_CACHE:
        _profile_add(widget_key, "temporary_mask_bytes_estimate", mask.nbytes)
        _profile_add(widget_key, "rgba_allocation_bytes_estimate", mask_W * mask_H * 4)

    t_shad0 = time.perf_counter_ns() if breakdown is not None else 0
    # Vectorized shadow layer
    if shadow_enabled and (distance > 0.0 or length > 0.0) and shad_opacity > 0.0:
        angle_rad = math.radians(shadow_angle)
        cos_a = math.cos(angle_rad)
        sin_a = math.sin(angle_rad)
        trail = np.zeros((mask_H, mask_W), dtype=np.uint8)
        if _PROFILE_EFFECT_CACHE:
            _profile_add(widget_key, "temporary_mask_bytes_estimate", trail.nbytes)
        steps = max(1, int(math.ceil(length)))
        for step in range(steps + 1):
            fraction = (step / steps) if length > 0.0 else 0.0
            reach = distance + length * fraction
            dx = int(round(cos_a * reach))
            dy = int(round(sin_a * reach))
            weight = 1.0 - shad_fade * fraction
            if weight <= 0.0:
                continue
            src_x0 = max(0, -dx)
            src_x1 = min(mask_W, mask_W - dx)
            src_y0 = max(0, -dy)
            src_y1 = min(mask_H, mask_H - dy)
            dst_x0 = max(0, dx)
            dst_x1 = min(mask_W, mask_W + dx)
            dst_y0 = max(0, dy)
            dst_y1 = min(mask_H, mask_H + dy)
            if src_x1 > src_x0 and src_y1 > src_y0:
                lut = _get_lut(weight)
                sub = cv2.LUT(mask[src_y0:src_y1, src_x0:src_x1], lut)
                cv2.max(trail[dst_y0:dst_y1, dst_x0:dst_x1], sub, dst=trail[dst_y0:dst_y1, dst_x0:dst_x1])
        if shad_opacity < 1.0:
            trail = cv2.LUT(trail, _get_lut(shad_opacity))
        if np.any(trail):
            tile = Image.new("RGBA", mask_size, (*shadow_color[:3], 0))
            if _PROFILE_EFFECT_CACHE:
                _profile_add(widget_key, "rgba_allocation_bytes_estimate", mask_W * mask_H * 4)
            tile.putalpha(Image.fromarray(trail, mode="L"))
            target_res = tile
            has_layer = True
    if breakdown is not None and profile_key:
        breakdown[f"{profile_key}.shadow"] = (time.perf_counter_ns() - t_shad0) / 1_000_000.0

    t_out0 = time.perf_counter_ns() if breakdown is not None else 0
    # Vectorized outline layer
    if width > 0 and outline_enabled and out_opacity > 0.0:
        if out_fade <= 0.0:
            kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (2 * width + 1, 2 * width + 1))
            expanded = cv2.dilate(mask, kernel)
        else:
            k3 = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
            expanded = np.zeros_like(mask)
            cur = mask
            for radius in range(1, width + 1):
                cur = cv2.dilate(cur, k3)
                weight = 1.0 - out_fade * (radius / (width + 1.0))
                if weight > 0.0:
                    lut = _get_lut(weight)
                    weighted = cv2.LUT(cur, lut)
                    cv2.max(expanded, weighted, dst=expanded)
        out_alpha = cv2.subtract(expanded, mask)
        if out_opacity < 1.0:
            out_alpha = cv2.LUT(out_alpha, _get_lut(out_opacity))
        if np.any(out_alpha):
            tile = Image.new("RGBA", mask_size, (*outline_color[:3], 0))
            if _PROFILE_EFFECT_CACHE:
                _profile_add(widget_key, "rgba_allocation_bytes_estimate", mask_W * mask_H * 4)
            tile.putalpha(Image.fromarray(out_alpha, mode="L"))
            if has_layer and target_res is not None:
                target_res.alpha_composite(tile)
            else:
                target_res = tile
                has_layer = True
    if breakdown is not None and profile_key:
        breakdown[f"{profile_key}.outline"] = (time.perf_counter_ns() - t_out0) / 1_000_000.0

    if target_res is None:
        target_res = Image.new("RGBA", mask_size, (0, 0, 0, 0))

    if use_sub:
        result = Image.new("RGBA", size, (0, 0, 0, 0))
        result.paste(target_res, (bx0, by0))
    else:
        result = target_res

    global _CACHED_BYTES
    entry_bytes = W * H * 4
    _CACHED_BYTES += entry_bytes
    _EFFECT_CACHE[cache_key] = (result, pad)
    while _CACHED_BYTES > 64 * 1024 * 1024 and len(_EFFECT_CACHE) > 1:
        popped_k, popped_val = _EFFECT_CACHE.popitem(last=False)
        if isinstance(popped_val, tuple) and isinstance(popped_val[0], Image.Image):
            _CACHED_BYTES -= popped_val[0].width * popped_val[0].height * 4

    if _PROFILE_EFFECT_CACHE:
        _profile_add(widget_key, "miss_render_ms", (time.perf_counter_ns() - miss_start_ns) / 1_000_000.0)
        _profile_add(widget_key, "cached_layer_bytes_estimate", W * H * 4)
    copy_start_ns = time.perf_counter_ns() if _PROFILE_EFFECT_CACHE else 0
    output = result.copy()
    if _PROFILE_EFFECT_CACHE:
        _profile_add(widget_key, "rgba_allocation_bytes_estimate", W * H * 4)
        _profile_add(widget_key, "cached_layer_copy_ms", (time.perf_counter_ns() - copy_start_ns) / 1_000_000.0)
    composite_start_ns = time.perf_counter_ns() if _PROFILE_EFFECT_CACHE else 0
    output.alpha_composite(image, (pad, pad))
    if _PROFILE_EFFECT_CACHE:
        _profile_add(
            widget_key,
            "current_rgb_composite_ms",
            (time.perf_counter_ns() - composite_start_ns) / 1_000_000.0,
        )
        _profile_add(widget_key, "total_ms", (time.perf_counter_ns() - profile_start_ns) / 1_000_000.0)
    if dynamic_key is not None:
        _EFFECT_CACHE[full_dyn_key] = output
    return output
