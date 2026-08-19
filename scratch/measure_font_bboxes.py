"""
Measure exact font textbbox values and bounding boxes for chart text.
"""
from pathlib import Path
import sys
sys.path.insert(0, str(Path("c:/_DEV/TeleM")))

from PIL import Image, ImageDraw, ImageFont
from src.indicators.helpers import load_font

font_path = "assets/Roboto-Bold.ttf"

for size in [12, 18, 24, 32, 48, 59]:
    font = load_font(font_path, size)
    dummy_img = Image.new("RGBA", (500, 200), (0, 0, 0, 0))
    draw = ImageDraw.Draw(dummy_img)
    
    print(f"\n--- Font Size: {size} px ---")
    for text in ["0%", "25%", "50%", "75%", "100%", "87", "116 rpm", "Cadence", "Heart Rate"]:
        bbox = draw.textbbox((0, 0), text, font=font)
        tw = bbox[2] - bbox[0]
        th = bbox[3] - bbox[1]
        print(f"  '{text:10s}': bbox=({bbox[0]:3d}, {bbox[1]:3d}, {bbox[2]:3d}, {bbox[3]:3d}) | tw={tw:3d}, th={th:3d}")
