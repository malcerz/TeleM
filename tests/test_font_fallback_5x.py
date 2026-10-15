"""ETAP 5X: per-glyph fallback for fonts without Polish letters."""
import os
from pathlib import Path

import pytest
from PIL import Image, ImageDraw, ImageFont

from src.indicators import font_fallback as ff
from src.indicators.helpers import (
    FONT_CACHE,
    draw_text_with_graphic_degree,
    load_font,
)

DIGITAL7 = Path(os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\Windows\Fonts\digital-7.ttf"))
ARIAL = Path(r"C:\Windows\Fonts\arial.ttf")
needs_fonts = pytest.mark.skipif(not (DIGITAL7.is_file() and ARIAL.is_file()), reason="fonts not installed")


def _render(font, text, size=(900, 200), **kw):
    img = Image.new("RGBA", size, (0, 0, 0, 0))
    ImageDraw.Draw(img).text((20, 30), text, font=font, fill=(255, 255, 255, 255), **kw)
    return img


@needs_fonts
def test_cmap_reader():
    d7 = ff.font_codepoints(str(DIGITAL7))
    ar = ff.font_codepoints(str(ARIAL))
    assert d7 is not None and ord("P") in d7 and ord("Ł") not in d7 and ord("°") not in d7
    assert ar is not None and all(ord(c) in ar for c in ff.POLISH_LETTERS)


@needs_fonts
@pytest.mark.parametrize("size", [24, 48, 96])
@pytest.mark.parametrize("text", ["PRZECHY", "25.4 km/h", "ISO 85", "-12.8"])
def test_primary_only_text_is_byte_identical(size, text):
    FONT_CACHE.clear()
    wrapped = load_font(str(DIGITAL7), size)
    assert isinstance(wrapped, ff.FallbackFreeTypeFont)
    plain = ImageFont.truetype(str(DIGITAL7), size)
    for kw in ({}, {"stroke_width": 3, "stroke_fill": (0, 0, 0, 255)}):
        assert _render(wrapped, text, **kw).tobytes() == _render(plain, text, **kw).tobytes()
    d = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    assert d.textbbox((0, 0), text, font=wrapped) == d.textbbox((0, 0), text, font=plain)
    assert d.textlength(text, font=wrapped) == d.textlength(text, font=plain)


@needs_fonts
@pytest.mark.parametrize("text", ["PRZECHYŁ", "ŚREDNIA PRĘDKOŚĆ", "WYSOKOŚĆ", "żółć ąę ńś ź"])
def test_polish_letters_use_fallback_on_primary_baseline(text):
    FONT_CACHE.clear()
    size = 64
    wrapped = load_font(str(DIGITAL7), size)
    plain = ImageFont.truetype(str(DIGITAL7), size)
    runs = wrapped._split(text)
    assert runs is not None
    for run, font in runs:
        missing = any(ord(c) not in ff.font_codepoints(str(DIGITAL7)) for c in run if ord(c) >= 128)
        assert (font is wrapped.fallback) == missing
    # Fallback glyphs differ from the primary's .notdef box.
    assert _render(wrapped, text).tobytes() != _render(plain, text).tobytes()
    # Primary-font letters keep their pixels: the leading ASCII run is unchanged.
    head = text.split(" ")[0]
    prefix = ""
    for ch in head:
        if ord(ch) >= 128:
            break
        prefix += ch
    if prefix:
        w = int(ImageDraw.Draw(Image.new("L", (1, 1))).textlength(prefix, font=plain))
        a = _render(wrapped, text).crop((0, 0, 20 + w - 2, 200))
        b = _render(plain, prefix).crop((0, 0, 20 + w - 2, 200))
        assert a.tobytes() == b.tobytes()
    # Baseline: anchor 'ls' bottom of caps equals the primary's.
    d = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    assert abs(d.textbbox((0, 0), "PRZECHYŁ", font=wrapped, anchor="ls")[3]
               - d.textbbox((0, 0), "PRZECHY", font=plain, anchor="ls")[3]) <= 1


@needs_fonts
def test_fallback_cap_height_matches_primary():
    FONT_CACHE.clear()
    wrapped = load_font(str(DIGITAL7), 80)
    prim = wrapped.getbbox("H", anchor="ls")
    fb = wrapped.fallback.getbbox("H", anchor="ls")
    assert abs((prim[3] - prim[1]) - (fb[3] - fb[1])) <= 2


@needs_fonts
@pytest.mark.parametrize("anchor", ["la", "ls", "mm", "rb", "lt", "md"])
def test_anchors_match_pillow_for_primary_runs(anchor):
    """The run layout used for mixed text reproduces Pillow's anchors."""
    FONT_CACHE.clear()
    wrapped = load_font(str(DIGITAL7), 60)
    plain = ImageFont.truetype(str(DIGITAL7), 60)
    runs = [("PRZECHY", wrapped)]
    _, length, box = wrapped._layout(runs, 0, ("", None, None, None))
    dx, dy = wrapped._anchor_shift(anchor, length, box)
    ref = plain.getbbox("PRZECHY", anchor=anchor)
    assert abs((box[0] + dx) - ref[0]) <= 1 and abs((box[1] + dy) - ref[1]) <= 1


@needs_fonts
def test_degree_symbol_stays_graphic():
    FONT_CACHE.clear()
    wrapped = load_font(str(DIGITAL7), 64)
    plain = ImageFont.truetype(str(DIGITAL7), 64)
    assert ord("°") not in (wrapped._covered or set()) and not wrapped._is_missing("°")
    for text in ("25.5°C", "-12.8°", "180°"):
        a = Image.new("RGBA", (500, 140)); b = Image.new("RGBA", (500, 140))
        draw_text_with_graphic_degree(ImageDraw.Draw(a), (10, 10), text, wrapped, fill=(255, 255, 255, 255),
                                      stroke_width=2, stroke_fill=(0, 0, 0, 255))
        draw_text_with_graphic_degree(ImageDraw.Draw(b), (10, 10), text, plain, fill=(255, 255, 255, 255),
                                      stroke_width=2, stroke_fill=(0, 0, 0, 255))
        assert a.tobytes() == b.tobytes()


@needs_fonts
def test_cache_and_fonts_with_polish_glyphs_not_wrapped():
    FONT_CACHE.clear()
    a = load_font(str(DIGITAL7), 40)
    assert load_font(str(DIGITAL7), 40) is a
    a._split("PRZECHYŁ")
    hits_before = len(a._runs)
    a._split("PRZECHYŁ")
    assert len(a._runs) == hits_before
    assert type(load_font(str(ARIAL), 40)) is ImageFont.FreeTypeFont


def test_broken_font_does_not_crash(tmp_path):
    bad = tmp_path / "broken.ttf"
    bad.write_bytes(b"\x00\x01\x00\x00garbage")
    assert ff.font_codepoints(str(bad)) is None
    font = ImageFont.load_default(size=20)
    assert ff.with_glyph_fallback(font, str(bad), 20) is font
