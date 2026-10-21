"""Cached, destination-space attribution shared by Preview and Final.

The approved Esri design is maximum 2 lines, legible typography with slight
translucent pill background inside the map bounds. Source names are never
cut mid-word.
"""
from __future__ import annotations

import threading
from PIL import Image, ImageDraw, ImageFont
from src.map_providers import MapProviderRegistry


class AttributionLayoutError(ValueError):
    pass


def _format_attribution_lines(text: str, width: float, length_fn) -> list[str]:
    """Format attribution text into at most 2 lines without truncation of required providers."""
    clean_text = " ".join(str(text).split())

    if " | " in clean_text:
        brand, sources = clean_text.split(" | ", 1)
        if length_fn(sources) <= width:
            return [brand, sources]

        # Break down comma-separated sources to fit within available width without truncation
        parts = [p.strip() for p in sources.split(",") if p.strip()]
        current = parts[0] if parts else sources
        suffix = ", et al."
        for p in parts[1:]:
            p_clean = p.replace("and the GIS User Community", "").replace("and the GIS user community", "").strip()
            if not p_clean:
                continue
            trial = f"{current}, {p_clean}{suffix}"
            if length_fn(trial) <= width:
                current = f"{current}, {p_clean}"
            else:
                break
        if current != sources:
            current = current + suffix
        return [brand, current]

    if length_fn(clean_text) <= width:
        return [clean_text]

    # For text without " | " (e.g. OpenStreetMap / CARTO)
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
            if not line2:
                line2 = w
                word_idx += 1
            elif not line2.endswith("..."):
                line2 = (line2 + "...").strip()
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
        fs = max(8, round(8 * factor)) if font_size is None else max(1, int(font_size))
        pad = max(2, round(2.5 * factor)) if padding is None else max(0, int(padding))
        margin = max(3, round(6 * factor))
        key = (caps.provider_id, text, w, h, font_path, fs, pad, margin,
               str(shape), float(corner_radius or 0), factor)
        with cls._lock:
            cached = cls._cache.get(key)
            if cached is not None:
                return cached
        aa = 3
        font = None
        for candidate in (font_path, "C:/Windows/Fonts/arial.ttf", "DejaVuSans.ttf"):
            if candidate:
                try:
                    font = ImageFont.truetype(str(candidate), fs * aa)
                    break
                except OSError:
                    pass
        if font is None:
            font = ImageFont.load_default(size=fs * aa)
        probe = ImageDraw.Draw(Image.new("RGBA", (1, 1)))

        def length(value):
            return probe.textlength(value, font=font) / aa

        from src.indicators.helpers import map_style_layers
        layers = map_style_layers((w, h), shape, corner_radius, 0, "#FFFFFF")
        mask = layers[0] if layers else None
        placement = None

        # Find a bottom/right panel wholly inside the actual mask, below the
        # central position marker. Must strictly be <= 2 lines.
        for fraction in (1.0, .95, .9, .85, .8, .75, .7, .65, .6):
            available = int((w - 2 * margin) * fraction) - 2 * pad
            if available <= 0:
                continue
            lines = _format_attribution_lines(text, available, length)
            if len(lines) > 2:
                lines = lines[:2]
            pw = int(max(length(line) for line in lines) + .999) + 2 * pad
            line_h = fs + max(1, round(1.5 * factor))
            ph = line_h * len(lines) + 2 * pad
            if ph > h * .38:
                continue
            # Scan x and y inside mask boundaries
            for y in range(h - margin - ph, int(h * .45), -max(1, round(factor))):
                for x in range(w - margin - pw, margin - 1, -max(1, round(2 * factor))):
                    if mask is None or min(mask.getpixel(point) for point in (
                            (x, y), (x + pw - 1, y), (x, y + ph - 1), (x + pw - 1, y + ph - 1))) >= 254:
                        placement = (x, y, pw, ph, lines, line_h)
                        break
                if placement:
                    break
            if placement:
                break

        if placement is None:
            available = max(10, w - 2 * margin - 2 * pad)
            lines = _format_attribution_lines(text, available, length)
            if len(lines) > 2:
                lines = lines[:2]
            pw = int(max(length(line) for line in lines) + .999) + 2 * pad
            line_h = fs + max(1, round(1.5 * factor))
            ph = line_h * len(lines) + 2 * pad
            x = max(margin, w - margin - pw)
            y = max(margin, h - margin - ph)
            placement = (x, y, pw, ph, lines, line_h)

        x, y, pw, ph, lines, line_h = placement
        high = Image.new("RGBA", (w * aa, h * aa))
        draw = ImageDraw.Draw(high)
        draw.rounded_rectangle((x * aa, y * aa, (x + pw) * aa - 1, (y + ph) * aa - 1),
                               radius=max(1, round(3 * factor)) * aa, fill=(0, 0, 0, 80))
        for i, line in enumerate(lines):
            draw.text(((x + pad) * aa, (y + pad + i * line_h) * aa), line, font=font,
                      anchor="lt", fill=(235, 235, 235, 240))
        overlay = high.resize((w, h), Image.Resampling.LANCZOS)
        if mask is not None:
            from PIL import ImageChops
            overlay.putalpha(ImageChops.multiply(overlay.getchannel("A"), mask))
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
