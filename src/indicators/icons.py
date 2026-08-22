"""Small procedural HUD glyphs used by configurable indicators.

The glyphs deliberately use Pillow primitives only: no font, bitmap asset, or
external dependency is involved.  This keeps CPU preview and GPU upload paths
on the same raster before compositing.
"""

from __future__ import annotations

from PIL import Image, ImageDraw

ICON_NAMES = ("none", "clock", "camera", "temperature", "battery", "solar")


def render_icon(name: str | None, size: int, *, fill=(255, 255, 255, 255), outline=(0, 0, 0, 230)):
    """Return a crisp square RGBA glyph, or ``None`` for no/unknown glyph."""
    name = str(name or "none").strip().lower()
    if name not in ICON_NAMES or name == "none":
        return None
    n = max(8, int(size))
    w = max(1, int(round(n * 1.18)))
    img = Image.new("RGBA", (w, n), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    lw = max(1, n // 12)
    cx, cy = w // 2, n // 2
    if name == "clock":
        r = max(3, n // 2 - lw - 1)
        d.ellipse((cx-r, cy-r, cx+r, cy+r), outline=outline, width=lw + 2)
        d.ellipse((cx-r+lw, cy-r+lw, cx+r-lw, cy+r-lw), outline=fill, width=lw)
        d.line((cx, cy, cx, cy-r//2), fill=fill, width=lw)
        d.line((cx, cy, cx+r//2, cy), fill=fill, width=lw)
    elif name == "camera":
        box = (lw + 1, n//3, w-lw-2, n-lw-2)
        d.rectangle(box, fill=outline)
        d.rectangle((box[0]+lw, box[1]+lw, box[2]-lw, box[3]-lw), fill=fill)
        d.rectangle((w//3, n//3-lw*2, 2*w//3, n//3+lw), fill=outline)
        r = max(2, n//5)
        d.ellipse((cx-r, cy-r, cx+r, cy+r), fill=outline)
        r2 = max(1, r-lw)
        d.ellipse((cx-r2, cy-r2, cx+r2, cy+r2), fill=fill)
    elif name == "temperature":
        stem_x = cx
        bulb_r = max(2, n//6)
        d.line((stem_x, n//5, stem_x, cy+bulb_r), fill=outline, width=lw+3)
        d.line((stem_x, n//5, stem_x, cy+bulb_r), fill=fill, width=lw)
        d.ellipse((stem_x-bulb_r-lw, cy, stem_x+bulb_r+lw, cy+2*bulb_r+lw), fill=outline)
        d.ellipse((stem_x-bulb_r, cy+lw, stem_x+bulb_r, cy+2*bulb_r), fill=fill)
        for yy in (n//3, n//2, 2*n//3):
            d.line((cx+bulb_r+lw*2, yy, w-lw, yy), fill=outline, width=max(1, lw//2))
    elif name == "battery":
        box = (lw+1, n//5, w-lw-3, n-n//5)
        d.rectangle(box, fill=outline)
        d.rectangle((box[0]+lw, box[1]+lw, box[2]-lw, box[3]-lw), fill=fill)
        d.rectangle((box[2], n//2-lw, w-1, n//2+lw), fill=outline)
        d.rectangle((box[0]+lw, box[1]+lw, box[0]+lw+max(2, (box[2]-box[0]-2*lw)*2//3), box[3]-lw), fill=fill)
    elif name == "solar":
        r = max(2, n//5)
        d.ellipse((cx-r, cy-r, cx+r, cy+r), fill=fill, outline=outline, width=lw)
        ray = max(2, n//2-lw)
        for dx, dy in ((0,-1),(1,0),(0,1),(-1,0),(1,-1),(1,1),(-1,1),(-1,-1)):
            d.line((cx+dx*(r+lw), cy+dy*(r+lw), cx+dx*ray, cy+dy*ray), fill=outline, width=lw)
    return img
