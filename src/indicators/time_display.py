"""Time display indicator rendering — multi-line info block.

Renders up to four configurable lines:
  - Date (YYYY-MM-DD)
  - Current time (HH:MM:SS) from GPMF
  - Elapsed time (HH:MM:SS or MM:SS)
  - Average speed (km/h)

Each line can be toggled on/off and styled independently via the layout config.
"""

from __future__ import annotations

from typing import Any, Optional

try:
    from PIL import Image, ImageDraw
except ImportError:
    Image = None  # type: ignore
    ImageDraw = None  # type: ignore

from src.indicators.helpers import load_font, parse_hex_color, s, _BoundedStaticCache, _static_cache_key
from src.indicators.icons import render_icon

# Fast bounded LRU caches for Time Display sub-components
_LINE_TILE_CACHE = _BoundedStaticCache(max_entries=64)
_ICON_CACHE = _BoundedStaticCache(max_entries=16)
_TEXT_METRIC_CACHE: dict[tuple, tuple[int, int]] = {}


def _get_text_metrics(font, font_path: str, fs: int, text: str, outline: int) -> tuple[int, int]:
    key = (font_path, fs, outline, text)
    m = _TEXT_METRIC_CACHE.get(key)
    if m is not None:
        return m
    tw = int(font.getlength(text) + outline * 4)
    lh = int(fs * 1.4)
    if len(_TEXT_METRIC_CACHE) > 256:
        _TEXT_METRIC_CACHE.clear()
    _TEXT_METRIC_CACHE[key] = (tw, lh)
    return tw, lh


def _get_line_tile(
    text: str,
    font_path: str,
    fs: int,
    fill: tuple[int, int, int, int],
    outline: int,
    tw: int,
    lh: int,
) -> Image.Image:
    key = _static_cache_key("td_line", font_path, fs, text, fill, outline, tw, lh)
    tile = _LINE_TILE_CACHE.get(key)
    if tile is not None:
        return tile

    font = load_font(font_path, fs)
    tile_h = int(fs * 2.0) + outline * 4
    tile_w = tw + outline * 4
    img = Image.new("RGBA", (tile_w, tile_h), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.text(
        (outline, outline),
        text,
        font=font,
        fill=fill,
        stroke_width=outline,
        stroke_fill=(0, 0, 0, 255),
    )
    _LINE_TILE_CACHE[key] = img
    return img


def _get_clock_icon(icon_name: str, icon_size: int) -> Optional[Image.Image]:
    if not icon_name or icon_name == "none":
        return None
    key = (icon_name, icon_size)
    ic = _ICON_CACHE.get(key)
    if ic is not None:
        return ic
    ic = render_icon(icon_name, icon_size)
    if ic is not None:
        _ICON_CACHE[key] = ic
    return ic


# ── Global master scale (Rozmiar) ─────────────────────────────────────────
# Legacy TeleM presets (v1..v10) store ``size`` as a fraction where 0.1 equals
# the standard scale (the old renderer multiplied it by 10).  The Property
# Editor now treats ``size`` as a direct master scale (1.0 = standard, 0.5 =
# half, 2.0 = double).  Normalise the legacy fraction so saved projects keep
# their exact look while new/edited configs use the intuitive semantics.
_TIME_DISPLAY_LEGACY_SIZE_MAX = 0.25


def _time_display_master_size(cfg: dict[str, Any]) -> float:
    """Resolve the time-display master scale from ``cfg['size']``.

    - ``size <= 0.25``  → legacy fraction (×10, so 0.1 → 1.0).
    - ``size >  0.25``  → direct master scale (1.0 = standard).
    """
    raw = float(cfg.get("size", 0.1))
    if raw <= _TIME_DISPLAY_LEGACY_SIZE_MAX:
        return raw * 10.0
    return raw


def render_time_display(
    canvas_w: int,
    canvas_h: int,
    layout: dict[str, Any],
    font_path: str,
    date_text: str,
    time_text: str,
    elapsed_seconds: float,
    avg_speed_kmh: float,
) -> tuple[Optional[Image.Image], int, int]:
    """Render the multi-line time display indicator.

    Lines are rendered from top to bottom in this order:
      1. Date (YYYY-MM-DD)        — if ``show_date`` is True
      2. Current time (HH:MM:SS)   — if ``show_time`` is True
      3. Elapsed time              — if ``show_elapsed`` is True
      4. Average speed             — if ``show_avg_speed`` is True

    Each line uses its own font size (``{prefix}_font_size``) and colour
    (``{prefix}_color``) from the layout config.  Falls back to the global
    ``font_size`` and a default grey/white when per-line values are absent.

    Args:
        canvas_w, canvas_h: Output image dimensions.
        layout: Full HUD layout dict.
        font_path: Path to TrueType font.
        date_text: Formatted date string (e.g. "2026-07-28").
        time_text: Formatted time string (e.g. "14:32:15").
        elapsed_seconds: Seconds since start of recording.
        avg_speed_kmh: Average speed in km/h.

    Returns:
        (overlay_img, px_x, px_y) or (None, 0, 0) if disabled or missing.
    """
    cfg = layout.get("indicators", {}).get("time_display")
    if cfg is None or not cfg.get("enabled", True):
        return None, 0, 0

    show_date = cfg.get("show_date", True)
    show_time = cfg.get("show_time", True)
    show_elapsed = cfg.get("show_elapsed", True)
    show_avg_speed = cfg.get("show_avg_speed", True)

    if not any([show_date, show_time, show_elapsed, show_avg_speed]):
        return None, 0, 0

    # ── Build formatted strings for computed fields ──────────────────
    elapsed_str = ""
    if show_elapsed:
        total = int(elapsed_seconds)
        hh = total // 3600
        mm = (total % 3600) // 60
        ss = total % 60
        if hh > 0:
            elapsed_str = f"{hh:02d}:{mm:02d}:{ss:02d}"
        else:
            elapsed_str = f"{mm:02d}:{ss:02d}"

    avg_speed_str = ""
    if show_avg_speed:
        avg_speed_str = f"{avg_speed_kmh:.1f} km/h"

    from src.indicators.helpers import _STATIC_CACHE

    # Rozmiar jest teraz globalną skalą master całego bloku.  Klucz cache musi
    # zawierać wszystkie parametry wpływające na wygląd (size, font_size, ikona,
    # per-line font sizes/colory/etykiety), inaczej zmiana "Rozmiar" w GUI nie
    # unieważniałaby cache i nic by się nie odświeżało.
    master = _time_display_master_size(cfg)
    _style_parts: list[Any] = []
    for _p in ("date", "time", "elapsed", "avg_speed"):
        _style_parts.append(cfg.get(f"{_p}_font_size"))
        _style_parts.append(cfg.get(f"{_p}_color"))
        _style_parts.append(cfg.get(f"{_p}_label"))
        _style_parts.append(cfg.get(f"show_{_p}_label", True))
    cache_key = _static_cache_key(
        "time_display", canvas_w, canvas_h, font_path,
        date_text, time_text, elapsed_str, avg_speed_str,
        show_date, show_time, show_elapsed, show_avg_speed,
        master,
        cfg.get("font_size", 0.025),
        cfg.get("icon", "none"),
        *_style_parts,
    )
    px_x = s(cfg["x"], canvas_w)
    px_y = s(cfg["y"], canvas_h)
    cached = _STATIC_CACHE.get(cache_key)
    if cached is not None:
        return cached, px_x, px_y

    # ── Line definitions ──────────────────────────────────────────────
    # (show_flag, text, config_prefix, default_color_rgb, default_label)
    line_defs: list[tuple[bool, str, str, tuple[int, int, int], str]] = [
        (show_date,      date_text,     "date",      (210, 210, 210), "Data"),
        (show_time,      time_text,     "time",      (255, 255, 255), "Godzina"),
        (show_elapsed,   elapsed_str,   "elapsed",   (255, 255, 255), "Czas"),
        (show_avg_speed, avg_speed_str, "avg_speed", (255, 255, 255), "Średnia prędkość"),
    ]

    min_dim = min(canvas_w, canvas_h)
    _global = layout.get("global", {}) if isinstance(layout, dict) else {}
    outline_raw = int(_global.get("text_outline", 3))
    outline = max(0, int(round(outline_raw * min_dim / 1000)))
    global_fs = max(14, s(cfg.get("font_size", 0.025), min_dim))

    # ── First pass: measure every enabled line ────────────────────────
    rendered_lines: list[tuple[str, int, tuple[int, int, int, int], int, int]] = []
    total_h = outline  # top padding
    max_w = 0
    for show, text, prefix, default_color, default_label in line_defs:
        if not show or not text:
            continue

        # ── Apply optional per-line label ───────────────────────────────
        show_lbl = cfg.get(f"show_{prefix}_label", True)
        lbl = cfg.get(f"{prefix}_label", default_label if show_lbl else "")
        if show_lbl and lbl:
            text = f"{lbl}: {text}"

        fs = max(1, int(s(cfg.get(f"{prefix}_font_size", global_fs), min_dim) * master))
        font = load_font(font_path, fs)
        # Parse colour from config, fall back to default
        color_str = cfg.get(f"{prefix}_color")
        if color_str:
            parsed = parse_hex_color(color_str)
            if parsed is not None:
                fill = parsed + (255,)  # add full alpha
            else:
                fill = default_color + (255,)
        else:
            fill = default_color + (255,)

        tw, lh = _get_text_metrics(font, font_path, fs, text, outline)
        rendered_lines.append((text, fs, fill, tw, lh))
        total_h += lh
        max_w = max(max_w, tw)

    if not rendered_lines:
        return None, 0, 0

    total_h += outline  # bottom padding

    # ── Create canvas ─────────────────────────────────────────────────
    # Ikona skaluje się razem z globalnym Rozmiarem (master).
    icon = _get_clock_icon(cfg.get("icon"), max(12, int(global_fs * master * 0.9)))
    icon_gap = max(2, int(global_fs * master * 0.18)) if icon else 0
    icon_w = (icon.width + icon_gap) if icon else 0

    tmp_w = int(max(max_w + outline * 2 + icon_w, s(0.3, canvas_w)))
    tmp_h = max(total_h, 80)
    tmp = Image.new("RGBA", (tmp_w, tmp_h), (0, 0, 0, 0))

    if icon:
        tmp.alpha_composite(icon, (outline, max(0, (tmp_h - icon.height) // 2)))

    # ── Second pass: composite each cached line tile ──────────────────
    text_x = outline + icon_w
    y = outline
    for text, fs, fill, tw, lh in rendered_lines:
        line_tile = _get_line_tile(text, font_path, fs, fill, outline, tw, lh)
        tmp.alpha_composite(line_tile, (text_x - outline, y - outline))
        y += lh

    bbox = tmp.getbbox()
    if not bbox:
        return None, 0, 0

    cropped = tmp.crop(bbox)
    _STATIC_CACHE[cache_key] = cropped
    return cropped, px_x, px_y
