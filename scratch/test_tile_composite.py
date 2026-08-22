import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from src.indicators.helpers import load_font

fs = 20
outline = 2
fill = (255, 255, 255, 255)
font = ImageFont.load_default()
text1 = "Date: 2026.08.14"
text2 = "Time: 11:18:10"
lh = int(fs * 1.4)

# Method A: Draw both lines on single canvas
img_a = Image.new("RGBA", (300, 100), (0, 0, 0, 0))
draw_a = ImageDraw.Draw(img_a)
draw_a.text((10, 10), text1, font=font, fill=fill, stroke_width=outline, stroke_fill=(0, 0, 0, 255))
draw_a.text((10, 10 + lh), text2, font=font, fill=fill, stroke_width=outline, stroke_fill=(0, 0, 0, 255))

# Method B: Draw each line on its own tile, then paste/composite
img_b = Image.new("RGBA", (300, 100), (0, 0, 0, 0))

# Tile 1
tw1 = int(font.getlength(text1) + outline * 4)
tile1 = Image.new("RGBA", (tw1, lh), (0, 0, 0, 0))
d1 = ImageDraw.Draw(tile1)
d1.text((0, 0), text1, font=font, fill=fill, stroke_width=outline, stroke_fill=(0, 0, 0, 255))

# Tile 2
tw2 = int(font.getlength(text2) + outline * 4)
tile2 = Image.new("RGBA", (tw2, lh), (0, 0, 0, 0))
d2 = ImageDraw.Draw(tile2)
d2.text((0, 0), text2, font=font, fill=fill, stroke_width=outline, stroke_fill=(0, 0, 0, 255))

img_b.alpha_composite(tile1, (10, 10))
img_b.alpha_composite(tile2, (10, 10 + lh))

arr_a = np.array(img_a)
arr_b = np.array(img_b)

diff = np.abs(arr_a.astype(np.int16) - arr_b.astype(np.int16)).max()
print(f"Diff between full canvas text vs composited tiles: {diff}")
