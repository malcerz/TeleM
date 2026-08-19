import sys
from pathlib import Path
from PIL import Image, ImageDraw

root = Path("c:/_DEV/TeleM")
sys.path.insert(0, str(root))
sys.path.insert(0, str(root / "src"))

from src.gui.layout_manager import normalize_layout, resolve_font_path
from src.indicators.helpers import s
from src.indicators.dispatcher import render_value_indicator

layout_path = root / "def_layout.json"
font_path = resolve_font_path("Arial")

resolutions = [
    (3840, 2160, "4K"),
    (1920, 1080, "1080p"),
    (1280, 720, "720p"),
    (854, 480, "480p"),
]

for w, h, name in resolutions:
    layout = normalize_layout(layout_path, w, h)
    for key in ["fit_cadence_text", "fit_heart_rate_text"]:
        cfg = layout["indicators"][key]
        img, rx, ry, _ = render_value_indicator(
            canvas_w=w, canvas_h=h,
            layout=layout, font_path=font_path,
            key=key, value=95.0, unit="rpm", label="Cadence",
            cfg_override=cfg, history_data=[80.0, 90.0, 95.0, 100.0],
        )
        if img:
            local_w, local_h = img.size
            final_left = int(round(rx - local_w / 2.0))
            final_top = int(round(ry - local_h / 2.0))
            final_right = final_left + local_w
            final_bottom = final_top + local_h
            overflow = final_bottom - h
            print(f"[{name}] {key}:")
            print(f"  Logical: x={cfg['x']} ({rx}px), y={cfg['y']} ({ry}px), size={cfg['size']}")
            print(f"  Local: w={local_w}, h={local_h}")
            print(f"  Final visual: left={final_left}, top={final_top}, right={final_right}, bottom={final_bottom}")
            print(f"  Overflow: {overflow}px (final_bottom - canvas_h = {final_bottom} - {h})")
