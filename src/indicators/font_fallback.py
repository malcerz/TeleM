"""Per-glyph font fallback for HUD text (ETAP 5X).

The user-selected font stays the primary font.  Only characters whose code
points are missing from the primary font's ``cmap`` (e.g. Polish letters in
Digital-7) are drawn with a fallback system font, run by run, on the primary
font's baseline and scaled to the primary cap height.  Text the primary font
fully covers is delegated unchanged to Pillow, so existing rasters stay
byte-identical.  The degree sign is never substituted: it is drawn as a
graphic ring by ``helpers.draw_text_with_graphic_degree``.
"""

from __future__ import annotations

import os
import struct
from collections import OrderedDict
from pathlib import Path
from typing import Any, Optional

from PIL import Image, ImageChops, ImageFont

# Candidates for the fallback font, in order.  TELEM_HUD_FALLBACK_FONT (a path)
# takes precedence.  System fonts are referenced in place, never copied.
FALLBACK_FONT_CANDIDATES: tuple[str, ...] = (
    r"C:\Windows\Fonts\segoeui.ttf",
    r"C:\Windows\Fonts\arial.ttf",
)

# Letters that trigger the wrapper; any other missing non-ASCII character is
# also substituted once the wrapper is active.
POLISH_LETTERS = "ąćęłńóśźżĄĆĘŁŃÓŚŹŻ"
_NEVER_SUBSTITUTE = frozenset("°")

_CMAP_CACHE: dict[str, Optional[frozenset[int]]] = {}


def _parse_cmap(path: str) -> Optional[frozenset[int]]:
    """Return the set of code points mapped by a TTF/OTF ``cmap`` (formats 4/12).

    Returns ``None`` when the table cannot be read (unknown format, TTC,
    damaged file); callers then use a raster probe instead.
    """
    try:
        data = Path(path).read_bytes()
        if data[:4] == b"ttcf":
            data_off = struct.unpack(">I", data[12:16])[0]
        else:
            data_off = 0
        num_tables = struct.unpack(">H", data[data_off + 4:data_off + 6])[0]
        cmap_off = None
        for i in range(num_tables):
            rec = data_off + 12 + 16 * i
            tag = data[rec:rec + 4]
            if tag == b"cmap":
                cmap_off = struct.unpack(">I", data[rec + 8:rec + 12])[0]
                break
        if cmap_off is None:
            return None
        n_sub = struct.unpack(">H", data[cmap_off + 2:cmap_off + 4])[0]
        codes: set[int] = set()
        parsed = False
        for i in range(n_sub):
            rec = cmap_off + 4 + 8 * i
            platform, encoding, sub_off = struct.unpack(">HHI", data[rec:rec + 8])
            if (platform, encoding) not in ((3, 1), (3, 10), (0, 3), (0, 4), (0, 6)):
                continue
            base = cmap_off + sub_off
            fmt = struct.unpack(">H", data[base:base + 2])[0]
            if fmt == 4:
                seg_x2 = struct.unpack(">H", data[base + 6:base + 8])[0]
                segs = seg_x2 // 2
                ends = struct.unpack(f">{segs}H", data[base + 14:base + 14 + seg_x2])
                starts_off = base + 16 + seg_x2
                starts = struct.unpack(f">{segs}H", data[starts_off:starts_off + seg_x2])
                deltas = struct.unpack(f">{segs}h", data[starts_off + seg_x2:starts_off + 2 * seg_x2])
                ro_off = starts_off + 2 * seg_x2
                ranges = struct.unpack(f">{segs}H", data[ro_off:ro_off + seg_x2])
                for s, (start, end, delta, ro) in enumerate(zip(starts, ends, deltas, ranges)):
                    for cp in range(start, min(end, 0xFFFE) + 1):
                        if ro == 0:
                            gid = (cp + delta) & 0xFFFF
                        else:
                            addr = ro_off + 2 * s + ro + 2 * (cp - start)
                            gid = struct.unpack(">H", data[addr:addr + 2])[0]
                            if gid:
                                gid = (gid + delta) & 0xFFFF
                        if gid:
                            codes.add(cp)
                parsed = True
            elif fmt == 12:
                n_groups = struct.unpack(">I", data[base + 12:base + 16])[0]
                for g in range(n_groups):
                    s_c, e_c, s_g = struct.unpack(">III", data[base + 16 + 12 * g:base + 28 + 12 * g])
                    for cp in range(s_c, e_c + 1):
                        if s_g + (cp - s_c):
                            codes.add(cp)
                parsed = True
        return frozenset(codes) if parsed else None
    except Exception:
        return None


def font_codepoints(path: str) -> Optional[frozenset[int]]:
    key = str(path)
    if key not in _CMAP_CACHE:
        _CMAP_CACHE[key] = _parse_cmap(key)
    return _CMAP_CACHE[key]


def _probe_missing(font: ImageFont.FreeTypeFont, ch: str) -> bool:
    """Raster fallback when cmap is unreadable: compare with a surely-missing glyph."""
    try:
        missing = font.getmask("\U0010FFFD")
        probe = font.getmask(ch)
        return probe.size == missing.size and bytes(probe) == bytes(missing)
    except Exception:
        return False


def _resolve_fallback_path() -> Optional[str]:
    override = os.environ.get("TELEM_HUD_FALLBACK_FONT", "").strip()
    for cand in ((override,) if override else ()) + FALLBACK_FONT_CANDIDATES:
        if cand and Path(cand).is_file():
            return cand
    return None


def _cap_height(font: ImageFont.FreeTypeFont) -> float:
    box = font.getbbox("H", anchor="ls")
    return float(box[3] - box[1])


class FallbackFreeTypeFont(ImageFont.FreeTypeFont):
    """FreeTypeFont that substitutes only glyphs missing from the primary font."""

    _RUN_CACHE_MAX = 256

    def __init__(self, path: str, size: int, fallback_path: str, covered: Optional[frozenset[int]]):
        super().__init__(path, size)
        self._covered = covered
        self._fallback_path = fallback_path
        prim_cap = _cap_height(self)
        fb = ImageFont.truetype(fallback_path, size)
        fb_cap = _cap_height(fb)
        if prim_cap > 0 and fb_cap > 0 and abs(prim_cap - fb_cap) >= 1:
            fb = ImageFont.truetype(fallback_path, max(1, int(round(size * prim_cap / fb_cap))))
        self.fallback = fb
        self._runs: OrderedDict[str, Optional[list[tuple[str, ImageFont.FreeTypeFont]]]] = OrderedDict()

    # ── run splitting ──────────────────────────────────────────────────
    def _is_missing(self, ch: str) -> bool:
        if ch in _NEVER_SUBSTITUTE or ord(ch) < 128:
            return False
        if self._covered is not None:
            return ord(ch) not in self._covered
        return _probe_missing(self, ch)

    def _split(self, text: str) -> Optional[list[tuple[str, ImageFont.FreeTypeFont]]]:
        """Runs of (text, font), or None when the primary font covers everything."""
        if not isinstance(text, str) or text.isascii():
            return None
        runs = self._runs.get(text)
        if runs is not None or text in self._runs:
            self._runs.move_to_end(text)
            return runs
        result: list[tuple[str, ImageFont.FreeTypeFont]] = []
        primary: ImageFont.FreeTypeFont = self
        for ch in text:
            font = self.fallback if self._is_missing(ch) else primary
            if result and result[-1][1] is font:
                result[-1] = (result[-1][0] + ch, font)
            else:
                result.append((ch, font))
        runs = result if any(f is self.fallback for _, f in result) else None
        self._runs[text] = runs
        if len(self._runs) > self._RUN_CACHE_MAX:
            self._runs.popitem(last=False)
        return runs

    def _run_length(self, run: str, font: ImageFont.FreeTypeFont, *args: Any) -> float:
        if font is self:
            return ImageFont.FreeTypeFont.getlength(self, run, *args)
        return font.getlength(run)

    def _layout(self, runs, stroke_width: int, args: tuple):
        """Pen positions and union bbox in left-baseline ('ls') space."""
        pens, x = [], 0.0
        x0 = y0 = float("inf")
        x1 = y1 = float("-inf")
        for run, font in runs:
            pens.append(x)
            if font is self:
                b = ImageFont.FreeTypeFont.getbbox(self, run, *args, stroke_width=stroke_width, anchor="ls")
            else:
                b = font.getbbox(run, stroke_width=stroke_width, anchor="ls")
            x0, y0 = min(x0, x + b[0]), min(y0, b[1])
            x1, y1 = max(x1, x + b[2]), max(y1, b[3])
            x += self._run_length(run, font, *args)
        return pens, x, (x0, y0, x1, y1)

    def _anchor_shift(self, anchor: Optional[str], length: float, box) -> tuple[float, float]:
        anchor = anchor or "la"
        h, v = anchor[0], anchor[1]
        ascent, descent = self.getmetrics()
        dx = {"l": 0.0, "m": -length / 2.0, "r": -length}.get(h, 0.0)
        dy = {
            "a": float(ascent), "s": 0.0, "d": -float(descent),
            "m": (float(ascent) - float(descent)) / 2.0,
            "t": -box[1], "b": -box[3],
        }.get(v, float(ascent))
        return dx, dy

    # ── Pillow font API ────────────────────────────────────────────────
    def getlength(self, text, mode="", direction=None, features=None, language=None):
        runs = self._split(text)
        if runs is None:
            return super().getlength(text, mode, direction, features, language)
        return sum(self._run_length(r, f, mode, direction, features, language) for r, f in runs)

    def getbbox(self, text, mode="", direction=None, features=None, language=None,
                stroke_width=0, anchor=None):
        runs = self._split(text)
        if runs is None:
            return super().getbbox(text, mode, direction, features, language, stroke_width, anchor)
        _, length, box = self._layout(runs, stroke_width, (mode, direction, features, language))
        dx, dy = self._anchor_shift(anchor, length, box)
        return (box[0] + dx, box[1] + dy, box[2] + dx, box[3] + dy)

    def getmask2(self, text, mode="", direction=None, features=None, language=None,
                 stroke_width=0, anchor=None, ink=0, start=None, *args, **kwargs):
        runs = self._split(text)
        if runs is None:
            return super().getmask2(text, mode, direction, features, language, stroke_width,
                                    anchor, ink, start, *args, **kwargs)
        pens, length, box = self._layout(runs, stroke_width, (mode, direction, features, language))
        dx, dy = self._anchor_shift(anchor, length, box)
        ox, oy = int(box[0]) - 1, int(box[1]) - 1
        width = max(1, int(box[2] - ox) + 2)
        height = max(1, int(box[3] - oy) + 2)
        canvas: Optional[Image.Image] = None
        for (run, font), pen in zip(runs, pens):
            if font is self:
                core, off = ImageFont.FreeTypeFont.getmask2(
                    self, run, mode, direction, features, language, stroke_width, "ls", ink, start,
                    *args, **kwargs)
            else:
                core, off = font.getmask2(run, mode, stroke_width=stroke_width, anchor="ls",
                                          ink=ink, start=start, *args, **kwargs)
            part = Image.Image()._new(core)
            if canvas is None:
                canvas = Image.new(part.mode, (width, height), 0)
            px, py = int(round(pen)) + off[0] - ox, off[1] - oy
            layer = Image.new(canvas.mode, canvas.size, 0)
            layer.paste(part, (px, py))
            canvas = ImageChops.lighter(canvas, layer)
        assert canvas is not None
        return canvas.im, (ox + int(round(dx)), oy + int(round(dy)))


def needs_fallback(path: str, font: ImageFont.FreeTypeFont) -> Optional[frozenset[int]]:
    """Return (cmap or empty marker) when the primary font lacks any Polish letter."""
    covered = font_codepoints(path)
    if covered is not None:
        missing = any(ord(ch) not in covered for ch in POLISH_LETTERS)
    else:
        missing = any(_probe_missing(font, ch) for ch in POLISH_LETTERS)
    return (covered if covered is not None else frozenset()) if missing else None


def with_glyph_fallback(font: Any, path: str, size: int) -> Any:
    """Wrap a loaded FreeType font when it lacks Polish glyphs; otherwise return it."""
    try:
        if os.environ.get("TELEM_HUD_GLYPH_FALLBACK", "1").strip() == "0":
            return font  # diagnostic A/B switch: legacy single-font rendering
        if type(font) is not ImageFont.FreeTypeFont or not path:
            return font
        cov = needs_fallback(path, font)
        if cov is None:
            return font
        fb_path = _resolve_fallback_path()
        if fb_path is None or Path(fb_path).resolve() == Path(path).resolve():
            return font
        covered = font_codepoints(path)
        return FallbackFreeTypeFont(path, int(size), fb_path, covered)
    except Exception:
        return font
