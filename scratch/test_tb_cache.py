"""Test render_time_block caching and execution."""
import json
import sys
from pathlib import Path
from PIL import Image
import numpy as np

root = Path("c:/_DEV/TeleM")
sys.path.insert(0, str(root))
sys.path.insert(0, str(root / "src"))

from src.indicators.time_block import render_time_block
from src.gui.layout_manager import resolve_font_path

layout = json.load(open("def_layout.json", "r", encoding="utf-8"))
font_path = resolve_font_path("Arial")

tb0, x0, y0 = render_time_block(1280, 720, layout, font_path, "2026-08-18", "06:46:25")
print(f"Frame 0 time_block: tb={tb0.size if tb0 else None} pos=({x0}, {y0})")

tb1, x1, y1 = render_time_block(1280, 720, layout, font_path, "2026-08-18", "06:46:25")
print(f"Frame 1 time_block: tb={tb1.size if tb1 else None} pos=({x1}, {y1})")

tb30, x30, y30 = render_time_block(1280, 720, layout, font_path, "2026-08-18", "06:46:26")
print(f"Frame 30 time_block: tb={tb30.size if tb30 else None} pos=({x30}, {y30})")
