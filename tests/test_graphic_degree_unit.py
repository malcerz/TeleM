from __future__ import annotations

import os
from PIL import Image, ImageDraw, ImageFont
import pytest

from src.indicators.helpers import (
    draw_graphic_degree_symbol,
    draw_text_with_graphic_degree,
    get_graphic_degree_metrics,
    load_font,
    measure_text_with_graphic_degree,
    split_text_degree_chunks,
)
from src.indicators.gauge import _render_compass_indicator
from src.indicators.lean import _render_lean_indicator
from src.indicators.text import _render_text_indicator
from src.indicators.bar import _text_size as bar_text_size, _draw_text_bounded as bar_draw_text_bounded
from src.indicators.custom_text import render_custom_text


def test_split_text_degree_chunks_no_font_for_degree():
    """Verify that degree '°' is extracted with font=None (vector graphic, no font glyph)."""
    font = load_font("arial", 24)

    # 1. '25°C'
    chunks = split_text_degree_chunks("25°C", font)
    assert len(chunks) == 3
    assert chunks[0] == ("25", font)
    assert chunks[1] == ("°", None)
    assert chunks[2] == ("C", font)

    # 2. '45°'
    chunks_45 = split_text_degree_chunks("45°", font)
    assert len(chunks_45) == 2
    assert chunks_45[0] == ("45", font)
    assert chunks_45[1] == ("°", None)

    # 3. '--°'
    chunks_dash = split_text_degree_chunks("--°", font)
    assert len(chunks_dash) == 2
    assert chunks_dash[0] == ("--", font)
    assert chunks_dash[1] == ("°", None)

    # 4. '°' alone
    chunks_solo = split_text_degree_chunks("°", font)
    assert len(chunks_solo) == 1
    assert chunks_solo[0] == ("°", None)

    # 5. Non-degree text
    chunks_plain = split_text_degree_chunks("100 km/h", font)
    assert len(chunks_plain) == 1
    assert chunks_plain[0] == ("100 km/h", font)


def test_graphic_degree_metrics_scaling():
    """Verify metrics scale proportionally with font size."""
    font_small = load_font("arial", 16)
    font_large = load_font("arial", 48)

    m_small = get_graphic_degree_metrics(font_small, stroke_width=1)
    m_large = get_graphic_degree_metrics(font_large, stroke_width=3)

    assert m_small["cap_h"] > 0
    assert m_large["cap_h"] > m_small["cap_h"]
    assert m_large["diameter"] > m_small["diameter"]
    assert m_large["thickness"] >= m_small["thickness"]
    assert m_large["advance"] > m_small["advance"]


def test_draw_graphic_degree_symbol_pixel_inspection():
    """Verify pixel output of the graphic degree ring: hollow center, filled ring, stroke."""
    img = Image.new("RGBA", (40, 40), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Draw at rect [10, 10, 30, 30] with thickness=2, stroke_width=2
    draw_graphic_degree_symbol(
        draw,
        (10, 10, 30, 30),
        thickness=2,
        fill=(255, 255, 255, 255),
        stroke_width=2,
        stroke_fill=(0, 0, 0, 255),
    )

    # Center (20, 20) should remain transparent (hollow interior)
    center_alpha = img.getpixel((20, 20))[3]
    assert center_alpha == 0, f"Expected hollow center at (20, 20), got alpha={center_alpha}"

    # Ring edge around x=11..12 or x=28..29 at y=20 should be white
    # Stroke edge around x=9 or x=31 at y=20 should be black
    has_white = any(img.getpixel((x, 20))[:3] == (255, 255, 255) for x in range(8, 33))
    has_black = any(img.getpixel((x, 20))[:3] == (0, 0, 0) and img.getpixel((x, 20))[3] > 0 for x in range(8, 33))
    assert has_white, "Expected white ring pixels"
    assert has_black, "Expected black stroke pixels"


def test_font_independence_across_different_fonts():
    """Verify graphic degree symbol renders reliably across different font families."""
    fonts_to_test = [
        load_font("arial", 28),
        load_font("segoeui", 28),
        ImageFont.load_default(),
    ]

    for f in fonts_to_test:
        img = Image.new("RGBA", (150, 60), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)

        w, h, bbox = measure_text_with_graphic_degree(draw, "180°", f, stroke_width=1)
        assert w > 0
        assert h > 0
        assert bbox[2] > bbox[0]
        assert bbox[3] > bbox[1]

        drawn_box = draw_text_with_graphic_degree(
            draw, (10, 10), "180°", font=f, fill=(255, 255, 0, 255), stroke_width=1, stroke_fill=(0, 0, 0, 255)
        )
        assert drawn_box[2] > drawn_box[0]
        assert drawn_box[3] > drawn_box[1]

        # Verify pixels were written
        non_empty_bbox = img.getbbox()
        assert non_empty_bbox is not None


def test_measure_and_draw_with_various_anchors():
    """Verify anchor alignment math (la, mm, ma, ra)."""
    font = load_font("arial", 30)
    img = Image.new("RGBA", (200, 100), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    for anc in ["la", "mm", "ma", "ra", "lt"]:
        w, h, bbox = measure_text_with_graphic_degree(draw, "45°", font, stroke_width=1, anchor=anc)
        assert w > 0
        assert h > 0

        drawn_box = draw_text_with_graphic_degree(
            draw, (100, 50), "45°", font=font, fill=(255, 255, 255, 255), stroke_width=1, stroke_fill=(0, 0, 0, 255), anchor=anc
        )
        assert drawn_box[2] > drawn_box[0]
        assert drawn_box[3] > drawn_box[1]


def test_compass_indicator_renders_graphic_heading():
    """Verify compass indicator renders dynamic heading text with graphic degree without error."""
    layout = {}
    cfg = {
        "x": 50, "y": 50, "size": 30,
        "compass_show_heading": True,
        "compass_heading_format": "03d",
        "show_units": True,
        "opacity": 1.0,
    }
    res, px, py, extra = _render_compass_indicator(
        canvas_w=1920, canvas_h=1080, layout=layout, font_path="",
        key="compass", value=42.0, unit="°", label="Heading",
        cfg=cfg, min_dim=1080, outline=2, fs=24, font=None,
        val_min=0, val_max=360, ticks=12, thickness=2, size_px=300, ss=1,
    )
    assert res is not None
    assert res.width > 0 and res.height > 0


def test_lean_indicator_renders_graphic_angle():
    """Verify lean indicator renders angle text with graphic degree without error."""
    layout = {}
    cfg = {
        "x": 50, "y": 50, "size": 25,
        "show_value": True,
        "show_label": True,
        "title": "LEAN",
        "max_angle": 45,
        "opacity": 1.0,
    }
    res, px, py, extra = _render_lean_indicator(
        canvas_w=1920, canvas_h=1080, layout=layout, font_path="",
        key="lean_indicator", value=18.5, unit="°", label="LEAN",
        cfg=cfg, min_dim=1080, outline=2, fs=22, font=None,
        val_min=-45, val_max=45, ticks=5, thickness=2, size_px=250, ss=1,
    )
    assert res is not None
    assert res.width > 0 and res.height > 0


def test_text_indicator_renders_graphic_degree():
    """Verify text indicator with unit '°C' renders with graphic degree."""
    layout = {}
    cfg = {
        "x": 10, "y": 10, "size": 3,
        "text_color": "#FF5500",
        "icon": "none",
    }
    res, px, py, extra = _render_text_indicator(
        canvas_w=1920, canvas_h=1080, layout=layout, font_path="",
        key="temp_text", value=24.3, unit="°C", label="Temp",
        cfg=cfg, min_dim=1080, outline=2, fs=26, font=None,
        val_min=0, val_max=50, ticks=0, thickness=2, size_px=100, ss=1,
    )
    assert res is not None
    assert res.width > 0 and res.height > 0


def test_bar_text_helpers_degree():
    """Verify bar text helpers handle text with degree."""
    img = Image.new("RGBA", (200, 100), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    font = load_font("arial", 20)

    w, h, box = bar_text_size(draw, "30°", font, stroke=1)
    assert w > 0 and h > 0

    bar_draw_text_bounded(
        draw, (10, 10), "30°", font=font, fill=(255, 255, 255, 255),
        stroke_width=1, stroke_fill=(0, 0, 0, 255), bounds=(200, 100), anchor="la"
    )
    assert img.getbbox() is not None


def test_custom_text_renders_graphic_degree():
    """Verify custom text overlay renders string with degree."""
    cfg = {
        "enabled": True,
        "text": "Temperature: 21°C",
        "x": 50, "y": 50,
        "font_size": 3.0,
        "color": "#FFFFFF",
    }
    res, px, py = render_custom_text(
        canvas_w=1920, canvas_h=1080, font_path="", cfg=cfg, stroke_width=2
    )
    assert res is not None
    assert res.width > 0 and res.height > 0
