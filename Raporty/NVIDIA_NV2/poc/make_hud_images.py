"""Generate test HUD images for the NV2 Gate-2 PoC.

Produces:
- hud_logical.png : 1920x1080 RGBA, logical (upright) layout with directional markers.
- hud_rot180.png  : same canvas, physically rotated 180 deg (pixel-exact, no resampling).
"""
from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

OUT = Path(__file__).resolve().parent
W, H = 1920, 1080


def _font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for cand in (
        "C:/Windows/Fonts/arialbd.ttf",
        "C:/Windows/Fonts/arial.ttf",
        "C:/Windows/Fonts/segoeui.ttf",
    ):
        try:
            return ImageFont.truetype(cand, size)
        except Exception:
            continue
    return ImageFont.load_default()


def make_logical() -> Image.Image:
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    f_big = _font(120)
    f_mid = _font(80)

    # Directional text
    d.text((W // 2 - 90, 40), "TOP", font=f_big, fill=(255, 255, 0, 255))
    d.text((W // 2 - 160, H - 160), "BOTTOM", font=f_big, fill=(0, 255, 255, 255))

    # Corner markers
    d.rectangle([20, 20, 220, 220], fill=(255, 0, 0, 255))            # red top-left
    d.ellipse([W - 220, H - 220, W - 20, H - 20], fill=(0, 0, 255, 255))  # blue bottom-right
    d.rectangle([W - 220, 20, W - 20, 220], fill=(0, 255, 0, 255))    # green top-right

    # Center up-arrow
    cx, cy = W // 2, H // 2
    d.polygon([(cx, cy - 200), (cx - 160, cy + 60), (cx + 160, cy + 60)], fill=(255, 128, 0, 255))
    d.rectangle([cx - 60, cy + 60, cx + 60, cy + 220], fill=(255, 128, 0, 255))

    # Gauge-like block at bottom-left (mimics speed gauge)
    d.rounded_rectangle([40, H - 260, 520, H - 40], radius=24, fill=(40, 40, 40, 200))
    d.text((90, H - 220), "123", font=f_big, fill=(255, 255, 255, 255))
    d.text((300, H - 170), "km/h", font=f_mid, fill=(200, 200, 200, 255))

    # Map-like block top-left (mimics track map)
    d.rounded_rectangle([260, 20, 900, 320], radius=24, fill=(30, 60, 30, 200))
    d.text((320, 60), "MAP", font=f_mid, fill=(255, 255, 255, 255))
    d.line([320, 200, 520, 140, 700, 240, 860, 120], fill=(0, 255, 0, 255), width=10)

    return img


def main() -> None:
    logical = make_logical()
    logical.save(OUT / "hud_logical.png")
    rot = logical.transpose(Image.Transpose.ROTATE_180)
    rot.save(OUT / "hud_rot180.png")
    print(f"wrote {OUT / 'hud_logical.png'} and {OUT / 'hud_rot180.png'}")


if __name__ == "__main__":
    main()
