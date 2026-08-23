import sys
from pathlib import Path
from PIL import Image, ImageDraw, ImageChops

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.indicators.helpers import load_font
from src.indicators.bar import _draw_text_bounded

font = load_font("", 10)
fill = (255, 255, 255, 255)
stroke_width = 1
stroke_fill = (0, 0, 0, 230)
bounds = (120, 200)
anchor = "lm"
xy = (55.0, 80.0)
text = "+3.7%"

# Reference method
img_ref = Image.new("RGBA", bounds, (0, 0, 0, 0))
d_ref = ImageDraw.Draw(img_ref)
_draw_text_bounded(d_ref, xy, text, font=font, fill=fill, stroke_width=stroke_width, stroke_fill=stroke_fill, bounds=bounds, anchor=anchor)

# Tile method
# 1. Build tile around (0, 0)
dummy = Image.new("RGBA", (16, 16), (0, 0, 0, 0))
d_dum = ImageDraw.Draw(dummy)
box = d_dum.textbbox((0, 0), text, font=font, anchor=anchor, stroke_width=stroke_width)
tw = box[2] - box[0]
th = box[3] - box[1]
tile = Image.new("RGBA", (tw, th), (0, 0, 0, 0))
d_tile = ImageDraw.Draw(tile)
d_tile.text((-box[0], -box[1]), text, font=font, fill=fill, stroke_width=stroke_width, stroke_fill=stroke_fill, anchor=anchor)

# 2. Composite tile
img_tile = Image.new("RGBA", bounds, (0, 0, 0, 0))
x, y = float(xy[0]), float(xy[1])
w, h = bounds
dx = 0.0
dy = 0.0
real_x0 = x + box[0]
real_x1 = x + box[2]
real_y0 = y + box[1]
real_y1 = y + box[3]
if real_x0 < 0:
    dx = -real_x0
elif real_x1 > w:
    dx = w - real_x1
if real_y0 < 0:
    dy = -real_y0
elif real_y1 > h:
    dy = h - real_y1

dest_x = int(round(x + box[0] + dx))
dest_y = int(round(y + box[1] + dy))
img_tile.alpha_composite(tile, (dest_x, dest_y))

diff = ImageChops.difference(img_ref, img_tile)
bbox = diff.getbbox()
print(f"Diff bbox between reference text and cached tile: {bbox}")
if bbox is None:
    print("SUCCESS: 100% BYTE-EXACT MATCH!")
else:
    print(f"Max delta: {diff.getextrema()}")
