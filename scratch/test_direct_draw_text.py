import sys
import time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PIL import Image, ImageDraw, ImageFont
from src.indicators.bar import _draw_text_bounded_cached, _draw_text_bounded
from src.indicators.helpers import load_font

w, h = 1316, 125
img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
font = load_font("arial.ttf", 24)

N = 1000

# Test 1: _draw_text_bounded_cached with varying text strings (cache miss every time)
t0 = time.perf_counter()
for i in range(N):
    target = img.copy()
    _draw_text_bounded_cached(
        target, (500.0, 50.0), f"{i*0.1:.1f} km",
        font=font, font_path="arial.ttf", fill=(255, 255, 255, 255),
        stroke_width=3, stroke_fill=(0, 0, 0, 230),
        bounds=(w, h), anchor="ma",
    )
t_cached_miss = (time.perf_counter() - t0) * 1000.0 / N

# Test 2: _draw_text_bounded (direct d.text clamped)
t0 = time.perf_counter()
for i in range(N):
    target = img.copy()
    d = ImageDraw.Draw(target)
    _draw_text_bounded(
        d, (500.0, 50.0), f"{i*0.1:.1f} km",
        font=font, fill=(255, 255, 255, 255),
        stroke_width=3, stroke_fill=(0, 0, 0, 230),
        bounds=(w, h), anchor="ma",
    )
t_direct = (time.perf_counter() - t0) * 1000.0 / N

# Test 3: direct d.text without textbbox recalculation if bounds are known to contain it
t0 = time.perf_counter()
for i in range(N):
    target = img.copy()
    d = ImageDraw.Draw(target)
    d.text((500.0, 50.0), f"{i*0.1:.1f} km", font=font, fill=(255, 255, 255, 255),
           stroke_width=3, stroke_fill=(0, 0, 0, 230), anchor="ma")
t_raw_text = (time.perf_counter() - t0) * 1000.0 / N

print(f"Timing Comparison for Text Drawing (varying values, N={N}):")
print(f"  1. _draw_text_bounded_cached (tile alloc + alpha_comp): {t_cached_miss:.4f} ms")
print(f"  2. _draw_text_bounded (d.textbbox + d.text)           : {t_direct:.4f} ms")
print(f"  3. Direct d.text(anchor='ma')                         : {t_raw_text:.4f} ms")
print(f"  Speedup Direct vs Cached Tile Alloc                   : {t_cached_miss / t_raw_text:.2f}x")
