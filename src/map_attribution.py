"""Cached, destination-space attribution shared by Preview and Final.

The approved Esri design is exactly 2 lines:
  Line 1: Powered by Esri. Source: Esri, Vantor,
  Line 2: Earthstar Geographics, and the GIS User Community

Typography is legible (~8-9 px on ~240 px map) with tight translucent black pill
background (alpha 80) inside the map bounds, aligned at bottom-left with <= 1%
bottom margin and tight ~1 px padding. Source names are never cut mid-word,
and synthetic abbreviations ('et al.') or generic phrases ('Esri and its licensors')
are strictly avoided in favor of the full provider names.
"""
from __future__ import annotations

import logging
import threading
import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageChops
from src.map_providers import MapProviderRegistry

logger = logging.getLogger(__name__)

CANONICAL_ESRI_LINE1 = "Powered by Esri. Source: Esri, Vantor,"
CANONICAL_ESRI_LINE2 = "Earthstar Geographics, and the GIS User Community"
CANONICAL_ESRI_LINES = [CANONICAL_ESRI_LINE1, CANONICAL_ESRI_LINE2]

KNOWN_ESRI_TOKENS = {
    "esri", "vantor", "maxar", "earthstar", "geographics", "gis", "user", "community",
    "powered", "by", "source:", "sources:", "and", "the", "|"
}


class AttributionLayoutError(ValueError):
    pass


def _format_attribution_lines(text: str, width: float, length_fn) -> list[str]:
    """Format attribution text into exactly 2 lines strictly adhering to provider licensing.

    Approved statutory Esri World Imagery attribution:
      Line 1: Powered by Esri. Source: Esri, Vantor,
      Line 2: Earthstar Geographics, and the GIS User Community

    Never injects unauthorized synthetic abbreviations such as 'et al.' or generic
    'Esri and its licensors' in place of actual data providers.
    """
    clean_text = " ".join(str(text).split())

    # Check for Esri satellite attribution
    is_esri = (
        "powered by esri" in clean_text.lower()
        or ("esri" in clean_text.lower() and any(
            k in clean_text.lower() for k in ("vantor", "earthstar", "gis user community", "maxar", "world imagery")
        ))
    )

    if is_esri:
        # Check if new providers appeared in metadata that require notice
        clean_words = set(w.strip(",.;()[]").lower() for w in clean_text.split() if w.strip(",.;()[]"))
        novel_tokens = clean_words - KNOWN_ESRI_TOKENS
        if novel_tokens:
            logger.warning(
                "Esri metadata wskazuje dodatkowych dostawców (%s). Wymagana weryfikacja dwuliniowego podpisu.",
                ", ".join(sorted(novel_tokens))
            )
        return list(CANONICAL_ESRI_LINES)

    if " | " in clean_text:
        brand, sources = clean_text.split(" | ", 1)
        return [brand.strip(), sources.strip()]

    if length_fn(clean_text) <= width:
        return [clean_text]

    # For non-Esri providers (e.g. OSM / CARTO)
    if ", " in clean_text:
        parts = [p.strip() for p in clean_text.split(",") if p.strip()]
        if len(parts) == 2 and length_fn(parts[0]) <= width and length_fn(parts[1]) <= width:
            return parts

    # Word wrapping for generic text across at most 2 lines without cutting words
    words = clean_text.split()
    line1 = ""
    line2 = ""
    word_idx = 0
    while word_idx < len(words):
        w = words[word_idx]
        trial = (line1 + " " + w).strip()
        if length_fn(trial) <= width:
            line1 = trial
            word_idx += 1
        else:
            break

    while word_idx < len(words):
        w = words[word_idx]
        trial = (line2 + " " + w).strip()
        if length_fn(trial) <= width:
            line2 = trial
            word_idx += 1
        else:
            break

    res = [l for l in (line1, line2) if l]
    return res if res else [clean_text]


class MapAttributionRenderer:
    _cache: dict[tuple, Image.Image] = {}
    _lock = threading.Lock()

    @classmethod
    def get_attribution_overlay(cls, provider_or_style, map_w, map_h,
                                font_path=None, font_size=None, padding=None,
                                *, text=None, shape="square", corner_radius=16,
                                scale=None):
        w, h = int(map_w), int(map_h)
        if w <= 0 or h <= 0:
            return None
        caps = MapProviderRegistry.get_capabilities(provider_or_style)
        if text is None:
            text = MapProviderRegistry.get_attribution(provider_or_style)[0]
        if not text:
            return None
        text = " ".join(str(text).split())
        factor = float(scale) if scale is not None else min(w, h) / 240.0
        # Base font size: orientacyjnie 8-9 px on ~240 px map (8.5 pt)
        base_fs = 8.5 * factor if font_size is None else float(font_size)
        pad = padding

        if min(w, h) < 100 or base_fs < 4.5:
            raise AttributionLayoutError("Zwiększ rozmiar mapy: atrybucja Esri nie mieści się na mapie")

        key = (caps.provider_id, text, w, h, font_path, round(base_fs, 2), pad,
               str(shape), float(corner_radius or 0), factor)
        with cls._lock:
            cached = cls._cache.get(key)
            if cached is not None:
                return cached

        aa = 3

        def _load_font(fsize_pt):
            for candidate in (font_path, "C:/Windows/Fonts/arial.ttf", "DejaVuSans.ttf"):
                if candidate:
                    try:
                        return ImageFont.truetype(str(candidate), int(round(fsize_pt * aa)))
                    except OSError:
                        pass
            return ImageFont.load_default(size=int(round(fsize_pt * aa)))

        probe = ImageDraw.Draw(Image.new("RGBA", (1, 1)))

        from src.indicators.helpers import map_style_layers
        layers = map_style_layers((w, h), shape, corner_radius, 0, "#FFFFFF")
        mask = layers[0] if layers else None

        # Bottom margin strictly <= 1% of map height (e.g. 2 px for 240 px map)
        margin_bottom = max(2, int(0.01 * h)) if h >= 200 else max(1, int(0.01 * h))
        margin_left = max(2, int(0.01 * w))

        avail_w = max(10, w - 2 * margin_left)
        lines = _format_attribution_lines(
            text, avail_w,
            lambda val: probe.textlength(val, font=_load_font(base_fs)) / aa
        )
        if len(lines) > 2:
            lines = lines[:2]

        text_block = "\n".join(lines)
        spacing = max(1, round(1.0 * aa))

        # Dynamic font scaling to guarantee text fits within avail_w
        fs = base_fs
        min_legible = 4.5
        while fs >= min_legible:
            font = _load_font(fs)
            mb = probe.multiline_textbbox((0, 0), text_block, font=font, spacing=spacing)
            ink_w_1x = (mb[2] - mb[0]) / aa
            ink_h_1x = (mb[3] - mb[1]) / aa
            pad_x = max(1, round(0.05 * ink_h_1x)) if padding is None else max(0, int(padding))
            if int(round(ink_w_1x + 2 * pad_x)) <= avail_w:
                break
            fs -= 0.1

        font = _load_font(fs)
        mb = probe.multiline_textbbox((0, 0), text_block, font=font, spacing=spacing)
        ink_x0, ink_y0, ink_x1, ink_y1 = mb
        ink_w_1x = (ink_x1 - ink_x0) / aa
        ink_h_1x = (ink_y1 - ink_y0) / aa

        # Inner padding: ~5% of text block height, min 1 px technical minimum
        pad_y = max(1, round(0.05 * ink_h_1x)) if padding is None else max(0, int(padding))
        pad_x = max(1, round(0.05 * ink_h_1x)) if padding is None else max(0, int(padding))

        pw = int(round(ink_w_1x + 2 * pad_x))
        ph = int(round(ink_h_1x + 2 * pad_y))

        # Bottom-left placement: bottom edge at map_bottom - margin_bottom (<= 1% h)
        target_x = margin_left
        target_y = h - margin_bottom - ph

        placement = None

        def _fits(px, py):
            if mask is None:
                return 0 <= px and 0 <= py and px + pw <= w and py + ph <= h
            if px < 0 or py < 0 or px + pw > w or py + ph > h:
                return False
            cropped = mask.crop((px, py, px + pw, py + ph))
            return cropped.getextrema()[0] >= 254

        if _fits(target_x, target_y):
            placement = (target_x, target_y)
        else:
            # If mask clips bottom-left (e.g. circle shape or rounded corners),
            # scan upward and inward to find lowest position fully within mask.
            step_y = max(1, round(factor))
            step_x = max(1, round(factor))
            for y_scan in range(target_y, int(h * 0.40), -step_y):
                for x_scan in range(margin_left, w - pw - margin_left + 1, step_x):
                    if _fits(x_scan, y_scan):
                        placement = (x_scan, y_scan)
                        break
                if placement:
                    break

        if placement is None:
            raise AttributionLayoutError("Zwiększ rozmiar mapy: atrybucja Esri nie mieści się na mapie")

        x, y = placement

        high = Image.new("RGBA", (w * aa, h * aa), (0, 0, 0, 0))
        draw = ImageDraw.Draw(high)

        rx0 = x * aa
        ry0 = y * aa
        rx1 = (x + pw) * aa - 1
        ry1 = (y + ph) * aa - 1
        corner_r = max(1, round(1.5 * aa))

        draw.rounded_rectangle((rx0, ry0, rx1, ry1), radius=corner_r, fill=(0, 0, 0, 80))

        tx = rx0 + pad_x * aa - ink_x0
        ty = ry0 + pad_y * aa - ink_y0
        draw.multiline_text((tx, ty), text_block, font=font, spacing=spacing, fill=(240, 240, 240, 255))

        overlay = high.resize((w, h), Image.Resampling.LANCZOS)
        if mask is not None:
            overlay.putalpha(ImageChops.multiply(overlay.getchannel("A"), mask))

        # Eliminate sub-2/255 Lanczos sinc ringing lobes and ensure RGB is strictly 0 where alpha is 0
        arr = np.array(overlay)
        arr[arr[:, :, 3] < 2, :] = 0
        overlay = Image.fromarray(arr)

        with cls._lock:
            if len(cls._cache) >= 128:
                cls._cache.pop(next(iter(cls._cache)))
            cls._cache[key] = overlay
        return overlay

    @classmethod
    def clear_cache(cls):
        with cls._lock:
            cls._cache.clear()


def map_attribution_overlay(style, size, cfg, *, shape_scale=1.0):
    """Esri attribution cannot be disabled by an old preset's show_attribution."""
    import os
    if (MapProviderRegistry.resolve_provider_id(style) != "satellite"
            and not cfg.get("show_attribution", False)
            and os.environ.get("TELEM_MAP_SHOW_ATTRIBUTION") != "1"):
        return None
    try:
        overlay = MapAttributionRenderer.get_attribution_overlay(
            style, *size, shape=cfg.get("map_shape", "square"),
            corner_radius=float(cfg.get("map_corner_radius", 16) or 0) * shape_scale)
    except AttributionLayoutError as exc:
        if MapProviderRegistry.resolve_provider_id(style) == "satellite":
            from src.integrations.esri import esri_client
            esri_client.layout_error = str(exc)
        raise
    if MapProviderRegistry.resolve_provider_id(style) == "satellite":
        from src.integrations.esri import esri_client
        esri_client.layout_error = ""
    return overlay


def apply_map_attribution(image, style, cfg, *, shape_scale=1.0):
    try:
        overlay = map_attribution_overlay(style, image.size, cfg, shape_scale=shape_scale)
    except AttributionLayoutError:
        # Do not display uncredited imagery or silently remove source names.
        from src.map_renderer import _placeholder
        from src.indicators.helpers import apply_map_shape
        return apply_map_shape(_placeholder(*image.size, "Zwiększ mapę"),
                               cfg.get("map_shape", "square"),
                               cfg.get("map_corner_radius", 16), scale=shape_scale)
    return Image.alpha_composite(image, overlay) if overlay is not None else image


def build_map_foreground_tile(size, style, cfg, marker_tile=None, marker_rect=None, *, shape_scale=1.0):
    """Static screen-space layer for AMD's existing marker texture slot.

    Native blends this slot after the map transform; text never rotates or
    pitches. The original marker pixels remain unchanged. Only attribution
    inherits map opacity, matching CPU Preview/Final.
    """
    from src.indicators.helpers import apply_map_opacity
    overlay = map_attribution_overlay(style, size, cfg, shape_scale=shape_scale)
    if overlay is None and MapProviderRegistry.resolve_provider_id(style) == "satellite":
        raise AttributionLayoutError("Esri: brak atrybucji; sprawdź połączenie w Ustawienia → Integracje")
    foreground = Image.new("RGBA", size)
    if overlay is not None:
        # Cached overlays are borrowed/read-only. Opacity==1 may return its
        # input, so copy before adding the existing marker to this layer.
        foreground = apply_map_opacity(overlay, cfg.get("opacity")).copy()
    if marker_tile is not None:
        foreground.alpha_composite(marker_tile, (marker_rect[0], marker_rect[1]))
    box = foreground.getbbox()
    if box is None:
        return None, (0, 0, 0, 0)
    x, y, right, bottom = box
    return foreground.crop(box), (x, y, right - x, bottom - y)
