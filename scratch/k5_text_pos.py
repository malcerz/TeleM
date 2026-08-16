"""ETAP 5K — check whether Pillow text rasterization is position-dependent.

Draws the same string at several integer origins on transparent canvases and
compares; also draws on a small tile at (-sl,-st) vs on the full canvas.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PIL import Image, ImageDraw
from src.indicators.helpers import load_font


def render_text_on(canvas_w, canvas_h, origin, text, font, color, outline):
    img = Image.new("RGBA", (canvas_w, canvas_h), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.text(origin, text, font=font, fill=color, stroke_width=outline,
           stroke_fill=(0, 0, 0, 255))
    return np.asarray(img, dtype=np.int16)


def main() -> int:
    font = load_font(str(ROOT / "include" / "mpv"), 30)
    text = "85.0 rpm"
    color = (255, 255, 255, 255)
    outline = 2

    # Draw on a large canvas at several integer origins.
    bases = {}
    for ox in (5, 1111, 2222):
        bases[ox] = render_text_on(4000, 511, (ox, 0), text, font, color, outline)
    print("=== position dependence (large canvas, integer origins) ===")
    for a in (5, 1111, 2222):
        for b in (5, 1111, 2222):
            if a < b:
                d = np.abs(bases[a] - bases[b])
                print(f"  origin {a} vs {b}: diff_px={(d.max(axis=2) > 0).sum()} MAX={d.max()}")

    # Compare a "tile-style" render (small canvas, origin (2,0)) against the
    # large-canvas render at (1111,0) after cropping to the glyph region.
    tile = render_text_on(45, 14, (2, 0), text, font, color, outline)
    big = bases[1111]
    # big glyph region for origin (1111,0) with stroke_bbox (-2,0,43,14) -> crop x[1109,1154)
    crop = big[0:14, 1109:1109 + 45]
    d = np.abs(tile - crop)
    print(f"\n=== tile(2,0) vs big(1111,0) cropped ===")
    print(f"  diff_px={(d.max(axis=2) > 0).sum()} MAE={d.mean():.3f} MAX={d.max()}")

    # Without stroke, does the mismatch persist?
    tile_ns = render_text_on(45, 14, (2, 0), text, font, color, 0)
    big_ns_img = Image.new("RGBA", (4000, 511), (0, 0, 0, 0))
    ImageDraw.Draw(big_ns_img).text((1111, 0), text, font=font, fill=color)
    big_ns = np.asarray(big_ns_img, dtype=np.int16)
    crop_ns = big_ns[0:14, 1109:1109 + 45]
    d2 = np.abs(tile_ns - crop_ns)
    print(f"\n=== no-stroke tile(2,0) vs big(1111,0) cropped ===")
    print(f"  diff_px={(d2.max(axis=2) > 0).sum()} MAE={d2.mean():.3f} MAX={d2.max()}")

    # Now the CRITICAL test: does drawing at (2,0) on the BIG canvas equal (1111,0)?
    big_at_2 = render_text_on(4000, 511, (2, 0), text, font, color, outline)
    # compare glyph region of big_at_2 (x[0,45)) vs big at 1111 (x[1109,1154))
    d3 = np.abs(big_at_2[0:14, 0:45] - crop)
    print(f"\n=== big(2,0) region vs big(1111,0) region ===")
    print(f"  diff_px={(d3.max(axis=2) > 0).sum()} MAE={d3.mean():.3f} MAX={d3.max()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
