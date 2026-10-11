"""Shared alpha-based outline and distance-faded shadow for HUD rasters.

Distances are logical pixels at 960x540; padding preserves the widget centre.
The original raster, including its existing stroke, is always composited last.
"""
from __future__ import annotations
import math
from PIL import Image, ImageChops, ImageFilter
from src.indicators.helpers import parse_hex_color


def effects_enabled(cfg):
    return bool(cfg.get("outline_enabled", False) or cfg.get("shadow_enabled", False))


def apply_indicator_effects(image, cfg, min_dim):
    if image is None or not effects_enabled(cfg):
        return image
    scale = min_dim / 540.0
    width = max(0, round(float(cfg.get("outline_width", 2.0)) * scale)) if cfg.get("outline_enabled") else 0
    distance = max(0.0, float(cfg.get("shadow_distance", 3.0)) * scale)
    length = max(0.0, float(cfg.get("shadow_length", 0.0)) * scale)
    shadow = bool(cfg.get("shadow_enabled"))
    pad = int(math.ceil(max(width, distance + length if shadow else 0))) + 2
    size = (image.width + 2 * pad, image.height + 2 * pad)
    mask = Image.new("L", size)
    mask.paste(image.getchannel("A"), (pad, pad))
    result = Image.new("RGBA", size)
    def layer(alpha, prefix):
        opacity = max(0.0, min(1.0, float(cfg.get(prefix + "_opacity", 0.7 if prefix == "shadow" else 1.0))))
        color = parse_hex_color(cfg.get(prefix + "_color", "#000000")) or (0,0,0)
        tile = Image.new("RGBA", size, (*color[:3], 0))
        tile.putalpha(alpha.point(lambda a: round(a * opacity)))
        return tile
    if shadow:
        angle = math.radians(float(cfg.get("shadow_angle", 45.0)))
        fade = max(0.0, min(1.0, float(cfg.get("shadow_fade", 1.0))))
        trail = Image.new("L", size)
        steps = max(1, int(math.ceil(length)))
        for step in range(steps + 1):
            fraction = step / steps if length else 0.0
            reach = distance + length * fraction
            shifted = Image.new("L", size)
            shifted.paste(mask, (round(math.cos(angle) * reach), round(math.sin(angle) * reach)))
            shifted = shifted.point(lambda a, weight=1.0-fade*fraction: round(a * weight))
            trail = ImageChops.lighter(trail, shifted)
        result.alpha_composite(layer(trail, "shadow"))
    if width:
        fade = max(0.0, min(1.0, float(cfg.get("outline_fade", 0.0))))
        expanded = Image.new("L", size)
        for radius in range(1, width + 1):
            dilation = mask.filter(ImageFilter.MaxFilter(2*radius+1))
            weight = 1.0 - fade * radius / (width + 1.0)
            expanded = ImageChops.lighter(expanded, dilation.point(lambda a, w=weight: round(a*w)))
        result.alpha_composite(layer(ImageChops.subtract(expanded, mask), "outline"))
    result.alpha_composite(image, (pad, pad))
    return result
