import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np
from PIL import Image, ImageDraw
from src.indicators.bar import _draw_text_bounded_cached, _draw_text_bounded
from src.indicators.helpers import load_font

w, h = 1316, 125
font = load_font("arial.ttf", 24)

img1 = Image.new("RGBA", (w, h), (0, 0, 0, 0))
img2 = Image.new("RGBA", (w, h), (0, 0, 0, 0))

# Method 1: cached tile
_draw_text_bounded_cached(
    img1, (500.0, 50.0), "15.4 km",
    font=font, font_path="arial.ttf", fill=(255, 255, 255, 255),
    stroke_width=3, stroke_fill=(0, 0, 0, 230),
    bounds=(w, h), anchor="ma",
)

# Method 2: direct draw bounded
d2 = ImageDraw.Draw(img2)
_draw_text_bounded(
    d2, (500.0, 50.0), "15.4 km",
    font=font, fill=(255, 255, 255, 255),
    stroke_width=3, stroke_fill=(0, 0, 0, 230),
    bounds=(w, h), anchor="ma",
)

a1 = np.asarray(img1)
a2 = np.asarray(img2)
diff = np.abs(a1.astype(np.int32) - a2.astype(np.int32))
max_diff = int(np.max(diff))
diff_px = int(np.sum(np.any(diff > 0, axis=-1)))
mae = float(np.mean(diff))

print("PARITY: _draw_text_bounded_cached vs _draw_text_bounded:")
print(f"  Max Diff:         {max_diff}")
print(f"  Different Pixels: {diff_px}")
print(f"  MAE:              {mae}")
if max_diff == 0:
    print("  -> EXACT 100% BIT-FOR-BIT IDENTICAL!")
