"""Experiment with thickness and ticks in gauge rendering."""
import sys
from pathlib import Path
from PIL import Image
import numpy as np

root = Path("c:/_DEV/TeleM")
sys.path.insert(0, str(root))
sys.path.insert(0, str(root / "src"))

from src.indicators.gauge import _render_gauge_indicator, _gauge_ticks
from src.indicators.helpers import s

out_dir = root / "Raporty" / "etap8m5_artifacts"
out_dir.mkdir(parents=True, exist_ok=True)

# Layout parameters
cfg = {
    "enabled": True, "label": "Enhanced Speed", "x": 50.0, "y": 80.0, "rotation": 0,
    "form": "gauge", "font_size": 2.4, "size": 12.5, "thickness": 1,
    "min_val": 0.0, "max_val": 40.0, "ticks": 10, "source": "fit",
    "show_marker": True, "marker_size": 5, "marker_color": "#ff0000",
    "show_units": True, "show_value": True, "decimals": 1,
}

canvas_w, canvas_h = 1920, 1080
min_dim = min(canvas_w, canvas_h)
size_px = s(cfg["size"], min_dim)  # 135 px
fs = max(8, s(cfg["font_size"], min_dim))
font_path = "assets/Roboto-Bold.ttf"

print(f"Canvas: {canvas_w}x{canvas_h}, min_dim={min_dim}, size_px={size_px}, fs={fs}")

# Test currently produced thickness = 1 vs various thickness values
for test_thick in [1, 3, 5, 8, 10]:
    for test_ticks in [4, 10, 20]:
        test_cfg = dict(cfg)
        test_cfg["ticks"] = test_ticks
        test_cfg["thickness"] = test_thick

        # Let's test with current thickness passed to _render_gauge_indicator:
        img_current, _, _, _ = _render_gauge_indicator(
            canvas_w=canvas_w, canvas_h=canvas_h, layout={"global": {}}, font_path=font_path,
            key="fit_enhanced_speed_text", value=25.4, unit="km/h", label="Speed",
            cfg=test_cfg, min_dim=min_dim, outline=3, fs=fs, font=None,
            val_min=0, val_max=40, ticks=test_ticks, thickness=test_thick, size_px=size_px, ss=1,
            formatted_val="25.4 km/h",
        )
        img_current.save(out_dir / f"gauge_thick{test_thick}_ticks{test_ticks}.png")
        arr = np.array(img_current)
        alpha = arr[:, :, 3]
        non_zero = np.count_nonzero(alpha > 0)
        print(f"thick={test_thick:2d}, ticks={test_ticks:2d} -> img size={img_current.size}, non_zero_alpha={non_zero}")
