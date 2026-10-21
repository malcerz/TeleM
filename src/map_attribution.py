"""Map Attribution Renderer for SportCamHUD.

Generates cached, resolution-scaled attribution overlays for map indicators
in Preview and Final export modes without per-frame re-rendering costs.
"""

from __future__ import annotations

import threading
from typing import Optional

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:
    Image = None  # type: ignore[assignment]
    ImageDraw = None  # type: ignore[assignment]
    ImageFont = None  # type: ignore[assignment]

from src.map_providers import MapProviderRegistry


class MapAttributionRenderer:
    """Thread-safe, statically cached attribution watermark generator for maps."""

    _cache: dict[tuple[str, int, int], Image.Image] = {}
    _lock = threading.Lock()

    @classmethod
    def get_attribution_overlay(
        cls,
        provider_or_style: str,
        map_w: int,
        map_h: int,
        font_path: Optional[str] = None,
        font_size: Optional[int] = None,
        padding: int = 4,
    ) -> Optional[Image.Image]:
        """Return a transparent RGBA image of size (map_w, map_h) containing the attribution.

        Cached statically across frames: 0 ms CPU time during video export.
        """
        if Image is None or map_w <= 0 or map_h <= 0:
            return None

        caps = MapProviderRegistry.get_capabilities(provider_or_style)
        text = caps.attribution_text
        if not text:
            return None

        cache_key = (caps.provider_id, int(map_w), int(map_h))
        with cls._lock:
            if cache_key in cls._cache:
                return cls._cache[cache_key]

        # Calculate responsive font size relative to map width (~2.5% of map width, min 8px, max 14px)
        fs = font_size or max(8, min(14, int(map_w * 0.026)))

        font = None
        if font_path:
            try:
                font = ImageFont.truetype(font_path, fs)
            except Exception:
                font = None
        if font is None:
            try:
                font = ImageFont.load_default()
            except Exception:
                font = None

        # Build overlay
        overlay = Image.new("RGBA", (map_w, map_h), (0, 0, 0, 0))
        d = ImageDraw.Draw(overlay)

        # Measure text box
        if hasattr(d, "textbbox") and font is not None:
            bbox = d.textbbox((0, 0), text, font=font)
            tw = bbox[2] - bbox[0]
            th = bbox[3] - bbox[1]
        elif hasattr(font, "getsize"):
            tw, th = font.getsize(text)
        else:
            tw, th = len(text) * (fs // 2), fs

        # Check if text fits in map width; if too wide, use a shorter attribution
        if tw + padding * 4 > map_w:
            short_text = text
            if "CARTO" in text:
                short_text = "© OSM, © CARTO"
            elif "OpenStreetMap" in text:
                short_text = "© OSM"
            elif "Esri" in text:
                short_text = "© Esri & contributors"

            if hasattr(d, "textbbox") and font is not None:
                bbox = d.textbbox((0, 0), short_text, font=font)
                tw = bbox[2] - bbox[0]
                th = bbox[3] - bbox[1]
            elif hasattr(font, "getsize"):
                tw, th = font.getsize(short_text)
            else:
                tw, th = len(short_text) * (fs // 2), fs
            text = short_text

        # Position at bottom-right corner of map
        x0 = max(0, map_w - tw - padding * 2 - 2)
        y0 = max(0, map_h - th - padding * 2 - 2)
        x1 = min(map_w - 1, x0 + tw + padding * 2)
        y1 = min(map_h - 1, y0 + th + padding * 2)

        # Discrete semi-transparent dark background pill
        d.rectangle((x0, y0, x1, y1), fill=(0, 0, 0, 160))

        # White legible text with slight outline
        tx = x0 + padding
        ty = y0 + padding
        if font:
            d.text((tx, ty), text, fill=(255, 255, 255, 240), font=font)
        else:
            d.text((tx, ty), text, fill=(255, 255, 255, 240))

        with cls._lock:
            cls._cache[cache_key] = overlay
            return overlay

    @classmethod
    def clear_cache(cls) -> None:
        """Clear cached overlay textures."""
        with cls._lock:
            cls._cache.clear()
