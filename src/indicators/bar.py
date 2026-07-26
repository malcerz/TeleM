"""Bar-form indicator rendering.

Extracted from ``overlay_renderer.py``.
"""

from __future__ import annotations

try:
    from PIL import Image, ImageDraw
except ImportError:
    Image = None  # type: ignore
    ImageDraw = None  # type: ignore

from src.indicators.helpers import s


def _render_bar_indicator(
    canvas_w, canvas_h, layout, font_path, key, value, unit, label,
    cfg, min_dim, outline, fs, font, val_min, val_max, ticks, thickness, size_px, ss,
    formatted_val=None,
):
    """Render a bar-form indicator."""
    w, h = int(size_px * ss), int(max(24, thickness * 6) * ss)
    img = Image.new("RGBA", (w + 40 * ss, h + 30 * ss), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    v_str = f"{value:.1f} {unit}"
    show_value = cfg.get("show_value", True)

    if label:
        draw.text(
            (20 * ss, 0), label, font=font,
            fill=(210, 210, 210, 255),
            stroke_width=outline, stroke_fill=(0, 0, 0, 255),
        )

    by = h - thickness - 5 * ss
    x1, x2 = 20 * ss, w + 20 * ss
    draw.line((x1, by, x2, by), fill=(160, 160, 160, 180), width=thickness * ss)

    if ticks > 1:
        for i in range(ticks + 1):
            xt = x1 + (w * i / ticks)
            draw.line(
                (xt, by - thickness * ss, xt, by + thickness * ss),
                fill=(245, 245, 245, 220),
                width=max(1, thickness // 4 * ss),
            )

    frac = max(0, min(1, (value - val_min) / (val_max - val_min))) if val_max > val_min else 0
    dot_x = x1 + frac * w
    dot_y = by

    draw.ellipse(
        (dot_x - thickness * ss, dot_y - thickness * ss,
         dot_x + thickness * ss, dot_y + thickness * ss),
        fill=(255, 50, 50, 255), outline=(255, 255, 255, 255),
    )
    extra = {
        "show_value": show_value, "value_text": v_str,
        "dot_x": dot_x / ss, "dot_y": dot_y / ss,
        "bar_w": w / ss, "bar_h": h / ss,
        "x1": x1 / ss, "x2": x2 / ss, "by": by / ss,
        "show_range_labels": cfg.get("show_range_labels", False),
        "left_text": f"{cfg.get('min_val', 0):.0f}",
        "right_text": f"{cfg.get('max_val', 100):.0f}",
    }
    if ss > 1:
        img = img.resize((int(img.width / ss), int(img.height / ss)), Image.LANCZOS)
    return img, s(cfg["x"], canvas_w), s(cfg["y"], canvas_h), extra
