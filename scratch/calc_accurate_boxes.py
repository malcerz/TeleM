import sys
from pathlib import Path
_root = Path(__file__).resolve().parent.parent
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

from src.gui.layout_manager import normalize_layout

layout = normalize_layout("def_layout.json", 1920, 1080)
canvas_w, canvas_h = 1920, 1080
min_dim = min(canvas_w, canvas_h)

indicators = layout.get("indicators", {})
custom_texts = layout.get("custom_texts", [])
enabled_indicators = {k: v for k, v in indicators.items() if v and v.get("enabled", True)}

boxes = []
for key, cfg in enabled_indicators.items():
    lx = cfg.get("x", 0.0)
    ly = cfg.get("y", 0.0)
    px = int(round((lx / 100.0) * canvas_w)) if lx <= 100.0 else int(round(lx))
    py = int(round((ly / 100.0) * canvas_h)) if ly <= 100.0 else int(round(ly))
    rot = int(cfg.get("rotation", 0)) % 360

    form = cfg.get("form", "text")
    if form == "gauge":
        sz = cfg.get("size", 0.1)
        size_px = int(round(sz * min_dim)) if sz <= 1.0 else int(round((sz / 100.0) * min_dim))
        radius = int(size_px * 1.35)
        x1, y1 = px - radius, py - radius
        x2, y2 = px + radius, py + radius
    elif form in ("bar", "segment_bar"):
        sz = cfg.get("size", 0.2)
        size_px = int(round(sz * canvas_w)) if sz <= 1.0 else int(round((sz / 100.0) * canvas_w))
        bar_w = size_px + 80
        bar_h = max(60, int(size_px * 0.35)) + 50
        if rot in (90, 270):
            w_bar, h_bar = bar_h, bar_w
        else:
            w_bar, h_bar = bar_w, bar_h
        x1 = px - w_bar // 2 - 20
        y1 = py - h_bar // 2 - 20
        x2 = px + w_bar // 2 + 20
        y2 = py + h_bar // 2 + 20
    elif form in ("chart", "moving_map", "static_map", "map"):
        cw = cfg.get("w", 0.35)
        ch = cfg.get("h", 0.25)
        w_px = int(round(cw * canvas_w)) if cw <= 1.0 else int(round((cw / 100.0) * canvas_w))
        h_px = int(round(ch * canvas_h)) if ch <= 1.0 else int(round((ch / 100.0) * canvas_h))
        x1, y1 = px - 20, py - 20
        x2, y2 = px + w_px + 30, py + h_px + 30
    elif key in ("time_block", "time_display") or "time" in key:
        x1, y1 = px - 20, py - 20
        x2, y2 = px + int(canvas_w * 0.18) + 20, py + int(canvas_h * 0.10) + 20
    else:
        # text indicator
        fs_val = cfg.get("font_size", cfg.get("size", 0.02))
        fs = max(10, int(round(fs_val * min_dim)) if fs_val <= 1.0 else int(round((fs_val / 100.0) * min_dim)))
        text_w = max(int(canvas_w * 0.10), fs * 10)
        text_h = max(int(canvas_h * 0.05), fs * 2 + 20)
        x1 = px - 20
        y1 = py - 20
        x2 = px + text_w + 20
        y2 = py + text_h + 20

    x1 = max(0, x1)
    y1 = max(0, y1)
    x2 = min(canvas_w, x2)
    y2 = min(canvas_h, y2)
    boxes.append({"key": key, "box": [x1, y1, x2, y2]})
    print(f"{key:25s}: [{x1:4d}, {y1:4d}, {x2:4d}, {y2:4d}] ({x2-x1}x{y2-y1})")
