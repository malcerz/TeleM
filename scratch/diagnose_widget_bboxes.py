"""Diagnose chart widget bboxes, placement, and canvas clipping across resolutions."""
import sys
from pathlib import Path

root = Path("c:/_DEV/TeleM")
sys.path.insert(0, str(root))
sys.path.insert(0, str(root / "src"))

from src.gui.layout_manager import normalize_layout
from src.indicators.helpers import s
from src.indicators.dispatcher import render_value_indicator

layout_path = root / "def_layout.json"

resolutions = [
    (3840, 2160, "4K"),
    (1920, 1080, "1080p"),
    (1280, 720, "720p"),
    (854, 480, "480p"),
]

for w, h, res_name in resolutions:
    layout = normalize_layout(layout_path, w, h)
    print(f"\n==================== [{res_name}] {w}x{h} ====================")
    for key in ["fit_cadence_text", "fit_heart_rate_text"]:
        cfg = layout["indicators"][key]
        img, rx, ry, _ = render_value_indicator(
            canvas_w=w, canvas_h=h, layout=layout, font_path="assets/Roboto-Bold.ttf",
            key=key, value=85.0, unit="rpm" if "cadence" in key else "BPM",
            label="Cadence" if "cadence" in key else "Heart Rate",
            cfg_override=cfg, history_data=[60.0, 80.0, 90.0],
        )
        
        # Logical widget bbox calculation as in compositor.py
        bw, bh = img.width, img.height
        center_x, center_y = rx, ry
        top_left_x = int(center_x - bw // 2)
        top_left_y = int(center_y - bh // 2)
        right = top_left_x + bw
        bottom = top_left_y + bh
        
        overflow_bottom = bottom - h
        overflow_right = right - w
        
        print(f"Indicator '{key}':")
        print(f"  Layout cfg: x={cfg['x']}%, y={cfg['y']}%, size={cfg['size']}%")
        print(f"  Logical Center: ({center_x}, {center_y})")
        print(f"  Local Render Size: {bw}x{bh}")
        print(f"  Final Visual BBox: left={top_left_x}, top={top_left_y}, right={right}, bottom={bottom}")
        print(f"  Bottom overflow: {overflow_bottom:+d} px (Clipped: {overflow_bottom > 0})")
        print(f"  Right overflow:  {overflow_right:+d} px (Clipped: {overflow_right > 0})")
