"""Text-form indicator rendering.

Extracted from ``overlay_renderer.py``.
"""

from __future__ import annotations

try:
    from PIL import Image, ImageDraw
except ImportError:
    Image = None  # type: ignore
    ImageDraw = None  # type: ignore

from src.indicators.helpers import s, parse_hex_color


def _render_text_indicator(
    canvas_w, canvas_h, layout, font_path, key, value, unit, label,
    cfg, min_dim, outline, fs, font, val_min, val_max, ticks, thickness, size_px, ss,
    formatted_val=None,
):
    """Render a text-form indicator."""
    v_str = formatted_val if formatted_val is not None else f"{value:.1f} {unit}"
    
    if label and v_str:
        txt = f"{label}: {v_str}"
    elif label:
        txt = label
    else:
        txt = v_str
        
    if not txt:
        return None, 0, 0, None
        
    text_color = parse_hex_color(cfg.get("text_color", "#FFFFFF")) or (255, 255, 255)
    
    txt_w = int(font.getlength(txt) + outline * 4)
    tmp = Image.new("RGBA", (txt_w, int(fs * 2)), (0, 0, 0, 0))
    draw = ImageDraw.Draw(tmp)
    draw.text(
        (outline, 0), txt, font=font,
        fill=(text_color[0], text_color[1], text_color[2], 255),
        stroke_width=outline, stroke_fill=(0, 0, 0, 255),
    )
    bbox = tmp.getbbox()
    if not bbox:
        return None, 0, 0, None
    return tmp.crop(bbox), s(cfg["x"], canvas_w), s(cfg["y"], canvas_h), None
