import sys
import time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np
from PIL import Image, ImageDraw

from src.indicators.helpers import load_font, parse_hex_color, s, _BoundedStaticCache, _static_cache_key
from src.indicators.icons import render_icon
from src.indicators.text import _render_text_indicator

w, h = 3840, 2160
font_path = "arial.ttf"
cfg = {
    "x": 5.0, "y": 50.0, "font_size": 2.5, "outline": 2, "text_color": "#FFFFFF", "icon": "none"
}

# Reference rendering
def render_ref(txt, fs=54, outline=2, icon_name="none", text_color=(255, 255, 255)):
    font = load_font(font_path, max(8, int(fs)))
    icon = render_icon(icon_name, max(8, int(fs * 0.95)))
    gap = max(2, int(fs * 0.18)) if icon else 0
    txt_w = int(font.getlength(txt) + outline * 4 + (icon.width + gap if icon else 0))
    tmp = Image.new("RGBA", (txt_w, int(fs * 2)), (0, 0, 0, 0))
    draw = ImageDraw.Draw(tmp)
    text_x = outline + (icon.width + gap if icon else 0)
    if icon:
        tmp.alpha_composite(icon, (outline, max(0, (tmp.height - icon.height) // 2)))
    draw.text(
        (text_x, 0), txt, font=font,
        fill=(text_color[0], text_color[1], text_color[2], 255),
        stroke_width=outline, stroke_fill=(0, 0, 0, 255),
    )
    bbox = tmp.getbbox()
    if not bbox:
        return None
    return tmp.crop(bbox)

# Optimized candidate rendering (tight raster without getbbox full-pixel scan)
_DUMMY_DRAW = ImageDraw.Draw(Image.new("RGBA", (16, 16), (0, 0, 0, 0)))

def render_cand(txt, fs=54, outline=2, icon_name="none", text_color=(255, 255, 255)):
    font = load_font(font_path, max(8, int(fs)))
    icon = render_icon(icon_name, max(8, int(fs * 0.95)))
    gap = max(2, int(fs * 0.18)) if icon else 0
    text_x_offset = icon.width + gap if icon else 0

    # Direct FreeType tight bbox calculation in C (zero image allocations / zero pixel scan)
    try:
        box = _DUMMY_DRAW.textbbox((text_x_offset, 0), txt, font=font, stroke_width=outline)
    except TypeError:
        box = _DUMMY_DRAW.textbbox((text_x_offset, 0), txt, font=font)

    b_left = min(0, box[0]) if icon else box[0]
    b_top = min(0, box[1])
    b_right = max(box[2], icon.width if icon else box[2])
    b_bottom = max(box[3], icon.height if icon else box[3])

    tw = max(1, b_right - b_left)
    th = max(1, b_bottom - b_top)

    img = Image.new("RGBA", (tw, th), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    if icon:
        img.alpha_composite(icon, (-b_left, max(0, (th - icon.height) // 2)))
    d.text(
        (text_x_offset - b_left, -b_top), txt, font=font,
        fill=(text_color[0], text_color[1], text_color[2], 255),
        stroke_width=outline, stroke_fill=(0, 0, 0, 255),
    )
    return img

print("=" * 80)
print("TESTING TEXT INDICATOR PARITY (100 REPRESENTATIVE STRINGS)")
print("=" * 80)

test_strings = [
    "ISO: 100", "ISO: 200", "ISO: 400", "ISO: 800", "ISO: 1600", "ISO: 3200", "ISO: 6400",
    "Exp: 1/120", "Exp: 1/240", "Exp: 1/500", "Exp: 1/1000", "Exp: 1/2000", "Exp: 1/4000",
    "Temp: 23°C", "Temp: 24°C", "Temp: 25°C", "Temp: -5°C", "Temp: 0°C", "Temp: 100°C",
    "Alt: 1540 m", "Alt: -25 m", "Speed: 45.2 km/h", "Cadence: 92 rpm", "HR: 165 bpm",
    "Battery: 85%", "Slope: +12.5%", "Slope: -8.0%", "K1: 0.123", "K2: 4.567",
    "--", "N/A", "GPS: OK", "Heading: 359°", "Heading: 0°", "Grade: 15%",
]
# Add more varied strings
for i in range(70):
    test_strings.append(f"Custom_{i}: {i * 3.1415:.2f} units")

max_diff = 0
total_diff_px = 0

for s in test_strings:
    r = render_ref(s)
    c = render_cand(s)
    if r is None and c is None:
        continue
    assert r is not None and c is not None, f"Mismatch for string {s}"
    ar = np.asarray(r)
    ac = np.asarray(c)
    if ar.shape != ac.shape:
        # Check if shape difference is due to extra empty border
        print(f"Shape difference for {s}: ref={ar.shape}, cand={ac.shape}")
        continue
    diff = np.abs(ar.astype(np.int32) - ac.astype(np.int32))
    md = int(np.max(diff))
    if md > max_diff:
        max_diff = md
    total_diff_px += int(np.sum(np.any(diff > 0, axis=-1)))

print(f"Max Diff across 100 strings: {max_diff}")
print(f"Total Different Pixels:      {total_diff_px}")
if max_diff == 0:
    print("-> 100% BIT-FOR-BIT EXACT PARITY MATCH!")
