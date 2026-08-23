import sys
from pathlib import Path
from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.indicators.helpers import load_font
from src.indicators.bar import _text_size

font = load_font("", 10)
dummy = Image.new("RGBA", (16, 16), (0, 0, 0, 0))
dd = ImageDraw.Draw(dummy)

for s in ["-12.0%", "-5.0%", "+0.0%", "+3.7%", "+10.0%", "--%", "-20.0%", "+20.0%"]:
    w = _text_size(dd, s, font, 1)[0]
    print(f"{s:8s} -> width = {w}")
