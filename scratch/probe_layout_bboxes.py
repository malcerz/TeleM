import json
import sys
from pathlib import Path
sys.path.insert(0, ".")

from src.indicators.helpers import s

layout = json.load(open("def_layout.json", encoding="utf-8"))
inds = layout.get("indicators", {})
w, h = 3840, 2160

bboxes = {}
for k, cfg in inds.items():
    if not cfg.get("enabled", True):
        continue
    x = s(cfg.get("x", 0), w)
    y = s(cfg.get("y", 0), h)
    form = cfg.get("form", "text")
    size = cfg.get("size", 0.08)
    size_px = s(size, min(w, h)) if isinstance(size, float) else 200
    print(f"Key: {k:<25} form: {form:<10} pos: ({x:6.1f}, {y:6.1f}) size_px: {size_px:5.1f}")

