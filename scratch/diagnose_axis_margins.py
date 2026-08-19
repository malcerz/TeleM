"""
Exact measurement of axis_bottom_margin vs actual label needs.
"""
import sys, math
from pathlib import Path
from PIL import Image, ImageDraw

root = Path("c:/_DEV/TeleM")
sys.path.insert(0, str(root))
sys.path.insert(0, str(root / "src"))

from src.gui.layout_manager import normalize_layout
from src.indicators.helpers import s, load_font
from src.indicators.chart_utils import _build_chart_bg

layout_path = root / "def_layout.json"
font_path = str(root / "assets/Roboto-Bold.ttf")

resolutions = [
    (3840, 2160, "4K"),
    (1920, 1080, "1080p"),
    (1280, 720, "720p"),
    (854, 480, "480p"),
]

print("=" * 80)
print("CHART_UTILS: axis_bottom_margin vs actual x-label needs")
print("=" * 80)

for canvas_w, canvas_h, res_name in resolutions:
    layout = normalize_layout(layout_path, canvas_w, canvas_h)
    cfg = layout["indicators"]["fit_cadence_text"]
    min_dim = min(canvas_w, canvas_h)
    outline_raw = int(layout["global"].get("text_outline", 3))
    outline = max(0, int(round(outline_raw * min_dim / 1000)))
    fs_val = cfg.get("font_size") if "font_size" in cfg else cfg.get("size", 0.02)
    fs = max(8, s(fs_val, min_dim))
    size_px = s(cfg["size"], canvas_w)
    chart_w = size_px
    chart_h = max(40, int(chart_w * 0.4))
    ss = 1  # AMD path uses ss=1

    print(f"\n[{res_name}] canvas={canvas_w}x{canvas_h} chart={chart_w}x{chart_h}")

    # Reproduce the _build_chart_bg logic step by step
    out_w, out_h = chart_w, chart_h
    width = chart_w * ss
    height = chart_h * ss

    # axis_bottom_margin_est:
    axis_bottom_margin_est = (int(max(6, height * 0.20)) if True else 0) * ss
    print(f"  axis_bottom_margin_est = int(max(6, {height} * 0.20)) * {ss} = {axis_bottom_margin_est}")

    # label_font_size calc
    plot_h_est = max(1, height - 4 * ss - axis_bottom_margin_est)
    label_fs_raw = int(max(7, min(width, height) * 0.13) * ss)
    label_fs = max(6, min(label_fs_raw, max(6, plot_h_est // 2)))
    print(f"  label_fs_raw={label_fs_raw}, plot_h_est={plot_h_est}, label_fs={label_fs}")

    # Measure actual x-label height
    try:
        font_axis = load_font(font_path, label_fs)
    except Exception:
        font_axis = None

    img_tmp = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw_tmp = ImageDraw.Draw(img_tmp)

    x_labels = ["0%", "25%", "50%", "75%", "100%"]
    label_100 = "100%"
    if font_axis:
        bbox = draw_tmp.textbbox((0, 0), label_100, font=font_axis)
        tw = bbox[2] - bbox[0]
        th = bbox[3] - bbox[1]
    else:
        tw = len(label_100) * 6
        th = 10

    # X labels drawn at: ty = plot_y2 + 5, height is th
    # plot_y2 = height - axis_bottom_margin
    axis_bottom_margin = axis_bottom_margin_est
    plot_y2 = height - axis_bottom_margin
    needed = 5 + th  # space needed below plot_y2 for X labels
    space_available = height - plot_y2  # = axis_bottom_margin
    
    print(f"  plot_y2={plot_y2}, axis_bottom_margin={axis_bottom_margin}")
    print(f"  x-label '100%': tw={tw}, th={th}")
    print(f"  x-label needs {needed}px below plot_y2, available={space_available}px")
    print(f"  x-label bottom in img: {plot_y2 + needed}px (img height={height})")
    
    overflow_in_chart_img = (plot_y2 + needed) - height
    print(f"  overflow in chart_img: {overflow_in_chart_img:+d}px  {'<< CLIPPED INTERNALLY!' if overflow_in_chart_img > 0 else 'OK'}")

    # Also check Y max-label (top)
    y_labels = ["77", "116"]
    max_label = "116"
    if font_axis:
        bbox_y = draw_tmp.textbbox((0, 0), max_label, font=font_axis)
        ty_max = bbox_y[3] - bbox_y[1]
    else:
        ty_max = 10
    axis_top_margin = int(math.ceil(max(4 * ss, ty_max / 2.0)))
    plot_y1 = axis_top_margin
    print(f"  axis_top_margin={axis_top_margin}, plot_y1={plot_y1}")
