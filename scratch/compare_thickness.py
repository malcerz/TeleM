"""Visual comparison of gauge with bugged thickness=1 vs corrected thickness."""
import sys
from pathlib import Path
from PIL import Image

root = Path("c:/_DEV/TeleM")
sys.path.insert(0, str(root))
sys.path.insert(0, str(root / "src"))

from src.indicators.gauge import _render_gauge_indicator
from src.indicators.helpers import s

out_dir = root / "Raporty" / "etap8m5_artifacts"
out_dir.mkdir(parents=True, exist_ok=True)

canvas_w, canvas_h = 1920, 1080
min_dim = 1080
size_px = s(12.5, min_dim)
fs = max(8, s(2.4, min_dim))
font_path = "assets/Roboto-Bold.ttf"

cfg_base = {
    "enabled": True, "label": "Enhanced Speed", "x": 50.0, "y": 80.0, "rotation": 0,
    "form": "gauge", "font_size": 2.4, "size": 12.5,
    "min_val": 0.0, "max_val": 40.0, "ticks": 10, "source": "fit",
    "show_marker": True, "marker_size": 5, "marker_color": "#ff0000",
    "show_units": True, "show_value": True, "decimals": 1,
}

# 1. Bugged (thickness = 1 px)
img_bugged, _, _, _ = _render_gauge_indicator(
    canvas_w=canvas_w, canvas_h=canvas_h, layout={"global": {}}, font_path=font_path,
    key="fit_enhanced_speed_text", value=16.8, unit="km/h", label="Speed",
    cfg=cfg_base, min_dim=min_dim, outline=3, fs=fs, font=None,
    val_min=0, val_max=40, ticks=10, thickness=1, size_px=size_px, ss=1,
    formatted_val="16.8 km/h",
)
img_bugged.save(out_dir / "compare_bugged_thickness1.png")

# 2. Corrected default (thickness = 6 px)
img_corrected, _, _, _ = _render_gauge_indicator(
    canvas_w=canvas_w, canvas_h=canvas_h, layout={"global": {}}, font_path=font_path,
    key="fit_enhanced_speed_text", value=16.8, unit="km/h", label="Speed",
    cfg=cfg_base, min_dim=min_dim, outline=3, fs=fs, font=None,
    val_min=0, val_max=40, ticks=10, thickness=6, size_px=size_px, ss=1,
    formatted_val="16.8 km/h",
)
img_corrected.save(out_dir / "compare_corrected_thickness6.png")

# 3. Thicker (thickness = 10 px)
img_thick10, _, _, _ = _render_gauge_indicator(
    canvas_w=canvas_w, canvas_h=canvas_h, layout={"global": {}}, font_path=font_path,
    key="fit_enhanced_speed_text", value=16.8, unit="km/h", label="Speed",
    cfg=cfg_base, min_dim=min_dim, outline=3, fs=fs, font=None,
    val_min=0, val_max=40, ticks=10, thickness=10, size_px=size_px, ss=1,
    formatted_val="16.8 km/h",
)
img_thick10.save(out_dir / "compare_thick10.png")

print("Saved comparison images to Raporty/etap8m5_artifacts/")
