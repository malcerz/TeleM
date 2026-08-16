"""ETAP 5K — check if Pillow text rasterization depends on the CANVAS WIDTH."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PIL import Image, ImageDraw
from src.indicators.helpers import load_font


def render_on(width, height, origin, text, font, color, outline):
    img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    ImageDraw.Draw(img).text(origin, text, font=font, fill=color,
                             stroke_width=outline, stroke_fill=(0, 0, 0, 255))
    return np.asarray(img, dtype=np.int16)


def main() -> int:
    font = load_font(str(ROOT / "include" / "mpv"), 30)
    text = "85.0 rpm"
    color = (255, 255, 255, 255)
    outline = 2

    # Draw the same text at the same origin on canvases of different widths.
    # Glyph region (origin 1111, stroke bbox -2..43, y 0..14) = [1109,1154] x [0,14].
    variants = {}
    for w in (1160, 2000, 4000):
        variants[w] = render_on(w, 511, (1111, 0), text, font, color, outline)
    print("=== canvas width dependence (same origin, cropped glyph region) ===")
    for a in (1160, 2000, 4000):
        for b in (1160, 2000, 4000):
            if a < b:
                ca = variants[a][0:14, 1109:1154]
                cb = variants[b][0:14, 1109:1154]
                d = np.abs(ca - cb)
                print(f"  width {a} vs {b}: diff_px={(d.max(axis=2) > 0).sum()} MAE={d.mean():.3f} MAX={d.max()}")

    # And origin close to the right edge: origin 1130 (glyph to 1173 > 1160 -> clipped).
    r = render_on(1160, 511, (1130, 0), text, font, color, outline)
    # Also compare origin 1100 on 1160 canvas to origin 1100 on 4000 canvas.
    v1100_1160 = render_on(1160, 511, (1100, 0), text, font, color, outline)
    v1100_4000 = render_on(4000, 511, (1100, 0), text, font, color, outline)
    d = np.abs(v1100_1160[0:14, 1098:1143] - v1100_4000[0:14, 1098:1143])
    print(f"\n=== origin 1100: width 1160 vs 4000 (cropped) ===")
    print(f"  diff_px={(d.max(axis=2) > 0).sum()} MAE={d.mean():.3f} MAX={d.max()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
