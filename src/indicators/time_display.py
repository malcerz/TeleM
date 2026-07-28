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

from src.indicators.helpers import load_font, parse_hex_color, s


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

    # ── Line definitions ──────────────────────────────────────────────
    # (show_flag, text, config_prefix, default_color_rgb, default_label)
    line_defs: list[tuple[bool, str, str, tuple[int, int, int], str]] = [
        (show_date,      date_text,   "date",      (210, 210, 210), "Data"),
        (show_time,      time_text,   "time",      (255, 255, 255), "Godzina"),
        (show_elapsed,   elapsed_str, "elapsed",   (255, 255, 255), "Czas"),
        (show_avg_speed, avg_speed_str, "avg_speed", (255, 255, 255), "Średnia prędkość"),
    ]

    min_dim = min(canvas_w, canvas_h)
    outline_raw = int(layout["global"].get("text_outline", 3))
    outline = max(0, int(round(outline_raw * min_dim / 1000)))
    global_fs = max(14, s(cfg.get("font_size", 0.025), min_dim))

    # ── Global size multiplier (Rozmiar w nagłówku) ──────────────────
    # value 0.001 → 0.01x (1 px),  0.1 → 1.0x (domyślny),
    # 0.5 → 5.0x,  1.0 → 10.0x (ok. 20% ekranu na linię)
    size_mult = cfg.get("size", 0.1) * 10

    # ── First pass: measure every enabled line ────────────────────────
    # Stores (text, font, line_height, fill_colour, text_width)
    rendered_lines: list[tuple[str, Any, int, tuple[int, int, int, int], int]] = []
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

        fs = max(1, int(s(cfg.get(f"{prefix}_font_size", global_fs), min_dim) * size_mult))
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
        lh = int(fs * 1.4)
        tw = int(font.getlength(text) + outline * 4)
        rendered_lines.append((text, font, lh, fill, tw))
        total_h += lh
        max_w = max(max_w, tw)

    if not rendered_lines:
        return None, 0, 0

    total_h += outline  # bottom padding

    # ── Create canvas ─────────────────────────────────────────────────
    tmp_w = int(max(max_w + outline * 2, s(0.3, canvas_w)))
    tmp_h = max(total_h, 80)
    tmp = Image.new("RGBA", (tmp_w, tmp_h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(tmp)

    # ── Second pass: render each line with its own font & colour ─────
    y = outline
    for text, font, lh, fill, tw in rendered_lines:
        draw.text(
            (outline, y),
            text,
            font=font,
            fill=fill,
            stroke_width=outline,
            stroke_fill=(0, 0, 0, 255),
        )
        y += lh

    bbox = tmp.getbbox()
    if not bbox:
        return None, 0, 0

    return tmp.crop(bbox), s(cfg["x"], canvas_w), s(cfg["y"], canvas_h)
