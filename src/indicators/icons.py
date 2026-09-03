"""TeleM HUD Icon Library & Renderer.

Provides a unified, crisp, scalable vector/raster icon set for TeleM HUD
indicators and common UI.  All glyphs are designed with consistent proportions,
clear silhouette readability at small/medium/large sizes, and optimal contrast
on dark and video backgrounds.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional, Tuple
from PIL import Image, ImageDraw, ImageFilter, ImageOps

# Assets directory for master icons
_ICONS_ROOT = Path(__file__).resolve().parents[1] / "assets" / "icons"
_PNG_DIR = _ICONS_ROOT / "png"
_SVG_DIR = _ICONS_ROOT / "svg"

# Canonical icon names list (preserves legacy first 6 items for 100% backward compatibility)
ICON_NAMES: tuple[str, ...] = (
    "none",
    "clock",
    "camera",
    "temperature",
    "battery",
    "solar",
    # Extended HUD Icon Set
    "stopwatch",
    "heart",
    "heart_pulse",
    "power",
    "bolt",
    "speedometer",
    "speed_wheel",
    "rocket",
    "mountain",
    "incline",
    "gopro",
    "shutter",
    "lens",
    "iso",
    "remote",
    "navigation",
    "compass",
    "pin",
    "location",
    "road",
    "route",
    "home",
    "satellite",
    "radar",
    "sun",
    "cloud",
    "bulb",
    "headlight",
    "snowflake",
    "car",
    "motorcycle",
    "dirt_bike",
    "drone",
    "drone_cam",
    "airplane",
    "helicopter",
    "boat",
    "snowmobile",
    "bike",
    "bike_front",
    "cyclist",
    "runner",
    "running_shoe",
    "skier",
    "snowboarder",
    "surfer",
    "diver",
    "paraglider",
    "skydiver",
    "muscle",
    "horse",
    "battery_empty",
    "battery_low",
    "battery_mid",
    "battery_full",
    "car_battery",
    "fuel",
    "oil_can",
    "oil_bottle",
    "gear",
    "gears",
    "gearshift",
    "piston",
    "brake_disc",
    "lean",
    "gyro",
    "gimbal",
    "helipad",
    "anchor",
    "arrow_up",
    "arrow_down",
    "arrow_up_down",
    "climb_arrow",
    "toggle_on",
    "toggle_off",
    "cube_3d",
)

# Friendly descriptions for GUI choice dropdowns
ICON_LABELS: dict[str, str] = {
    "none": "Brak",
    "clock": "Zegar (czas)",
    "stopwatch": "Stoper",
    "camera": "Aparat / Kamera",
    "gopro": "GoPro / Action Cam",
    "temperature": "Temperatura",
    "battery": "Bateria (standard)",
    "battery_empty": "Bateria pusta",
    "battery_low": "Bateria niska (1/3)",
    "battery_mid": "Bateria średnia (2/3)",
    "battery_full": "Bateria pełna",
    "car_battery": "Akumulator pojazdu",
    "solar": "Solar / Słońce",
    "sun": "Słońce (jasność)",
    "cloud": "Chmura (pogoda)",
    "bulb": "Żarówka (światło)",
    "headlight": "Reflektor",
    "snowflake": "Śnieżynka (mróz)",
    "heart": "Serce (tętno)",
    "heart_pulse": "Serce z pulsem (EKG)",
    "power": "Błyskawica (moc)",
    "bolt": "Piorun (moc)",
    "speedometer": "Prędkościomierz",
    "speed_wheel": "Koło prędkości",
    "rocket": "Rakieta (wznoszenie)",
    "mountain": "Góry (wysokość n.p.m.)",
    "incline": "Nachylenie / Kąt stoku",
    "navigation": "Kursor nawigacji",
    "compass": "Kompas",
    "pin": "Pinezka (lokalizacja)",
    "location": "Lokalizacja",
    "road": "Droga (dystans)",
    "route": "Trasa",
    "home": "Dom (punkt startu)",
    "satellite": "Satelita (GPS)",
    "radar": "Radar / Zasięg",
    "shutter": "Migawka aparatu",
    "lens": "Obiektyw",
    "iso": "Czułość ISO",
    "remote": "Aparatura RC / Pilot",
    "car": "Samochód",
    "motorcycle": "Motocykl",
    "dirt_bike": "Cross / Enduro",
    "drone": "Dron (quadcopter)",
    "drone_cam": "Dron z kamerą",
    "airplane": "Samolot",
    "helicopter": "Helikopter",
    "boat": "Łódź / Motorówka",
    "snowmobile": "Skuter śnieżny",
    "bike": "Rower",
    "bike_front": "Rower (przód)",
    "cyclist": "Kolarz",
    "runner": "Biegacz",
    "running_shoe": "But biegowy",
    "skier": "Narciarz",
    "snowboarder": "Snowboardzista",
    "surfer": "Surfer",
    "diver": "Płetwonurek",
    "paraglider": "Paralotniarz",
    "skydiver": "Spadochroniarz",
    "muscle": "Biceps (siła)",
    "horse": "Koń (jeździectwo)",
    "fuel": "Dystrybutor paliwa",
    "oil_can": "Oliwiarka",
    "oil_bottle": "Butelka oleju",
    "gear": "Koło zębate (kadencja)",
    "gears": "Zębatki (napęd)",
    "gearshift": "Skrzynia biegów",
    "piston": "Tłok silnika",
    "brake_disc": "Tarcza hamulcowa",
    "lean": "Przechył (horyzont)",
    "gyro": "Żyroskop",
    "gimbal": "Gimbal 3D",
    "helipad": "Lądowisko H",
    "anchor": "Kotwica",
    "arrow_up": "Strzałka w górę",
    "arrow_down": "Strzałka w dół",
    "arrow_up_down": "Strzałka góra/dół",
    "climb_arrow": "Wznoszenie (tempo)",
    "toggle_on": "Włącznik ON",
    "toggle_off": "Włącznik OFF",
    "cube_3d": "Kostka 3D",
}

# Semantic aliases for effortless mapping
ICON_ALIASES: dict[str, str] = {
    "time": "clock",
    "timer": "stopwatch",
    "temp": "temperature",
    "gpmf": "gopro",
    "speed": "speedometer",
    "cadence": "gear",
    "hr": "heart",
    "bpm": "heart_pulse",
    "alt": "mountain",
    "altitude": "rocket",
    "elevation": "mountain",
    "gps": "satellite",
    "tilt": "lean",
    "slope": "incline",
    "dist": "road",
    "distance": "road",
    "bat": "battery",
    "accu": "car_battery",
    "gas": "fuel",
    "rpm": "gear",
}

# Master image cache in RAM to avoid re-reading disk
_MASTER_CACHE: dict[str, Image.Image] = {}

# Sized and tinted render cache
_ICON_RENDER_CACHE: dict[tuple[str, int, Tuple[int, int, int, int], Tuple[int, int, int, int]], Image.Image] = {}
_MAX_CACHE_ENTRIES = 512


def _load_master_icon(name: str) -> Optional[Image.Image]:
    """Load the high-resolution 256x256 RGBA master asset for an icon."""
    if name in _MASTER_CACHE:
        return _MASTER_CACHE[name]

    png_path = _PNG_DIR / f"{name}.png"
    if png_path.is_file():
        try:
            img = Image.open(png_path).convert("RGBA")
            _MASTER_CACHE[name] = img
            return img
        except Exception:
            pass

    return None


def _procedural_fallback(name: str, size: int, fill: tuple, outline: tuple) -> Optional[Image.Image]:
    """Procedural fallback if disk assets are missing or inaccessible."""
    n = max(8, int(size))
    w = max(1, int(round(n * 1.18)))
    img = Image.new("RGBA", (w, n), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    lw = max(1, n // 12)
    cx, cy = w // 2, n // 2

    if name == "clock":
        r = max(3, n // 2 - lw - 1)
        d.ellipse((cx - r, cy - r, cx + r, cy + r), outline=outline, width=lw + 2)
        d.ellipse((cx - r + lw, cy - r + lw, cx + r - lw, cy + r - lw), outline=fill, width=lw)
        d.line((cx, cy, cx, cy - r // 2), fill=fill, width=lw)
        d.line((cx, cy, cx + r // 2, cy), fill=fill, width=lw)
    elif name == "camera":
        box = (lw + 1, n // 3, w - lw - 2, n - lw - 2)
        d.rectangle(box, fill=outline)
        d.rectangle((box[0] + lw, box[1] + lw, box[2] - lw, box[3] - lw), fill=fill)
        d.rectangle((w // 3, n // 3 - lw * 2, 2 * w // 3, n // 3 + lw), fill=outline)
        r = max(2, n // 5)
        d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=outline)
        r2 = max(1, r - lw)
        d.ellipse((cx - r2, cy - r2, cx + r2, cy + r2), fill=fill)
    elif name == "temperature":
        stem_x = cx
        bulb_r = max(2, n // 6)
        d.line((stem_x, n // 5, stem_x, cy + bulb_r), fill=outline, width=lw + 3)
        d.line((stem_x, n // 5, stem_x, cy + bulb_r), fill=fill, width=lw)
        d.ellipse((stem_x - bulb_r - lw, cy, stem_x + bulb_r + lw, cy + 2 * bulb_r + lw), fill=outline)
        d.ellipse((stem_x - bulb_r, cy + lw, stem_x + bulb_r, cy + 2 * bulb_r), fill=fill)
    elif name == "battery":
        box = (lw + 1, n // 5, w - lw - 3, n - n // 5)
        d.rectangle(box, fill=outline)
        d.rectangle((box[0] + lw, box[1] + lw, box[2] - lw, box[3] - lw), fill=fill)
        d.rectangle((box[2], n // 2 - lw, w - 1, n // 2 + lw), fill=outline)
        d.rectangle((box[0] + lw, box[1] + lw, box[0] + lw + max(2, (box[2] - box[0] - 2 * lw) * 2 // 3), box[3] - lw), fill=fill)
    elif name == "solar":
        r = max(2, n // 5)
        d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=fill, outline=outline, width=lw)
        ray = max(2, n // 2 - lw)
        for dx, dy in ((0, -1), (1, 0), (0, 1), (-1, 0), (1, -1), (1, 1), (-1, 1), (-1, -1)):
            d.line((cx + dx * (r + lw), cy + dy * (r + lw), cx + dx * ray, cy + dy * ray), fill=outline, width=lw)
    else:
        # Generic dot
        d.ellipse((cx - n // 3, cy - n // 3, cx + n // 3, cy + n // 3), fill=fill, outline=outline, width=lw)

    return img


def render_icon(
    name: str | None,
    size: int,
    *,
    fill: Tuple[int, int, int, int] = (255, 255, 255, 255),
    outline: Tuple[int, int, int, int] = (0, 0, 0, 230),
) -> Optional[Image.Image]:
    """Return a crisp RGBA glyph scaled to target size, or ``None`` for no/unknown glyph."""
    if not name:
        return None
    raw = str(name).strip().lower()
    if raw in ("none", "", "0", "false", "off"):
        return None

    # Resolve alias
    canonical = ICON_ALIASES.get(raw, raw)
    if canonical not in ICON_NAMES:
        return None

    # Check cache
    cache_key = (canonical, int(size), tuple(fill), tuple(outline))
    if cache_key in _ICON_RENDER_CACHE:
        return _ICON_RENDER_CACHE[cache_key]

    target_h = max(8, int(size))
    master = _load_master_icon(canonical)

    if master is None:
        result = _procedural_fallback(canonical, target_h, fill, outline)
        if result is not None:
            if len(_ICON_RENDER_CACHE) > _MAX_CACHE_ENTRIES:
                _ICON_RENDER_CACHE.clear()
            _ICON_RENDER_CACHE[cache_key] = result
        return result

    # Calculate scaled dimensions preserving aspect ratio
    mw, mh = master.size
    aspect = mw / max(1.0, float(mh))
    target_w = max(1, int(round(target_h * aspect)))

    # Resample master with high quality Lanczos filter
    resample_filter = Image.Resampling.LANCZOS if hasattr(Image, "Resampling") else Image.LANCZOS
    scaled = master.resize((target_w, target_h), resample_filter)

    # Tint if fill is custom (master is white + alpha)
    r_f, g_f, b_f, a_f = fill
    if (r_f, g_f, b_f) != (255, 255, 255) or a_f != 255:
        r, g, b, a = scaled.split()
        # Tint RGB channels
        r_tint = ImageMath.eval("convert(r * rf / 255, 'L')", r=r, rf=r_f) if hasattr(Image, "ImageMath") else r
        # Simple color tint
        color_img = Image.new("RGBA", scaled.size, (r_f, g_f, b_f, 255))
        if a_f < 255:
            a = a.point(lambda p: int(p * a_f / 255))
        color_img.putalpha(a)
        scaled = color_img

    # Outline / contrast shadow generation if requested and visible
    o_r, o_g, o_b, o_a = outline
    if o_a > 0:
        # Create an outline padding around the icon for crisp contrast on video
        out_pad = max(1, target_h // 16)
        padded_w = target_w + out_pad * 2
        padded_h = target_h + out_pad * 2
        out_img = Image.new("RGBA", (padded_w, padded_h), (0, 0, 0, 0))

        # Alpha mask of the scaled icon
        alpha_mask = scaled.getchannel("A")

        # Fast 4-way or 8-way dilation for crisp stroke
        outline_mask = Image.new("L", (padded_w, padded_h), 0)
        for dx in range(-out_pad, out_pad + 1):
            for dy in range(-out_pad, out_pad + 1):
                if dx * dx + dy * dy <= out_pad * out_pad + 1:
                    outline_mask.paste(alpha_mask, (out_pad + dx, out_pad + dy), alpha_mask)

        outline_layer = Image.new("RGBA", (padded_w, padded_h), (o_r, o_g, o_b, o_a))
        outline_layer.putalpha(outline_mask)

        # Composite outline behind scaled icon
        out_img.alpha_composite(outline_layer)
        out_img.alpha_composite(scaled, (out_pad, out_pad))
        result = out_img
    else:
        result = scaled

    # Cache result
    if len(_ICON_RENDER_CACHE) > _MAX_CACHE_ENTRIES:
        _ICON_RENDER_CACHE.clear()
    _ICON_RENDER_CACHE[cache_key] = result
    return result


def clear_icon_cache() -> None:
    """Clear in-memory icon caches."""
    _MASTER_CACHE.clear()
    _ICON_RENDER_CACHE.clear()
