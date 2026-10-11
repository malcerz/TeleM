"""Shared alpha-based outline and distance-faded shadow for HUD rasters.

Accelerated via vectorized OpenCV morphological dilation and NumPy array slicing.
Supports both modern 0–100% scale (effects_version: 2) and legacy 540p logical px.
Padding preserves the widget centre; original raster composited on top.
"""
from __future__ import annotations

import math
from hashlib import blake2b
from typing import Any
import numpy as np
import cv2
from PIL import Image

from src.indicators.helpers import _BoundedStaticCache, parse_hex_color

_EFFECT_CACHE = _BoundedStaticCache(max_entries=128)
_LUT_CACHE: dict[float, np.ndarray] = {}


def clear_effects_cache() -> None:
    """Clear all cached effect rasters."""
    _EFFECT_CACHE.clear()


def get_effects_cache_stats() -> dict[str, Any]:
    """Return cache statistics for diagnostics."""
    return _EFFECT_CACHE.stats()


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


def apply_indicator_effects(image: Image.Image | None, cfg: dict[str, Any] | None, min_dim: int) -> Image.Image | None:
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
    src_alpha = np.array(image.getchannel("A"), dtype=np.uint8)
    if not np.any(src_alpha):
        return image

    content_hash = blake2b(src_alpha.tobytes(), digest_size=16).digest()
    cache_key = (content_hash, image.size, cfg_sig)
    cached = _EFFECT_CACHE.get(cache_key)
    if cached is not None:
        effect_layer, pad = cached
        result = effect_layer.copy()
        result.alpha_composite(image, (pad, pad))
        return result

    # Compute bounds and padding
    raw_pad = max(width, (distance + length) if shadow_enabled else 0.0)
    pad = int(math.ceil(raw_pad)) + 2
    W = image.width + 2 * pad
    H = image.height + 2 * pad
    size = (W, H)

    mask = np.zeros((H, W), dtype=np.uint8)
    mask[pad:pad + image.height, pad:pad + image.width] = src_alpha
    result = Image.new("RGBA", size, (0, 0, 0, 0))

    # Vectorized shadow layer
    if shadow_enabled and (distance > 0.0 or length > 0.0) and shad_opacity > 0.0:
        angle_rad = math.radians(shadow_angle)
        cos_a = math.cos(angle_rad)
        sin_a = math.sin(angle_rad)
        trail = np.zeros((H, W), dtype=np.uint8)
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
            src_x1 = min(W, W - dx)
            src_y0 = max(0, -dy)
            src_y1 = min(H, H - dy)
            dst_x0 = max(0, dx)
            dst_x1 = min(W, W + dx)
            dst_y0 = max(0, dy)
            dst_y1 = min(H, H + dy)
            if src_x1 > src_x0 and src_y1 > src_y0:
                lut = _get_lut(weight)
                sub = lut[mask[src_y0:src_y1, src_x0:src_x1]]
                np.maximum(trail[dst_y0:dst_y1, dst_x0:dst_x1], sub, out=trail[dst_y0:dst_y1, dst_x0:dst_x1])
        if shad_opacity < 1.0:
            trail = _get_lut(shad_opacity)[trail]
        if np.any(trail):
            tile = Image.new("RGBA", size, (*shadow_color[:3], 0))
            tile.putalpha(Image.fromarray(trail, mode="L"))
            result.alpha_composite(tile)

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
                    weighted = lut[cur]
                    np.maximum(expanded, weighted, out=expanded)
        out_alpha = cv2.subtract(expanded, mask)
        if out_opacity < 1.0:
            out_alpha = _get_lut(out_opacity)[out_alpha]
        if np.any(out_alpha):
            tile = Image.new("RGBA", size, (*outline_color[:3], 0))
            tile.putalpha(Image.fromarray(out_alpha, mode="L"))
            result.alpha_composite(tile)

    _EFFECT_CACHE[cache_key] = (result, pad)
    output = result.copy()
    output.alpha_composite(image, (pad, pad))
    return output
