"""
Diagnose real axis_bottom_margin vs actual x-label needs with real system font.
"""
import sys, math
from pathlib import Path
from PIL import Image, ImageDraw

root = Path("c:/_DEV/TeleM")
sys.path.insert(0, str(root))
sys.path.insert(0, str(root / "src"))

from src.gui.layout_manager import normalize_layout, resolve_font_path
from src.indicators.helpers import s, load_font

layout_path = root / "def_layout.json"
font_path = resolve_font_path("Arial")
print(f"Real font_path: {font_path}\n")

resolutions = [
    (3840, 2160, "4K"),
    (1920, 1080, "1080p"),
    (1280, 720, "720p"),
    (854, 480, "480p"),
]

print("=" * 80)
print("REAL FONT: axis_bottom_margin vs actual x-label needs")
print("=" * 80)

for canvas_w, canvas_h, res_name in resolutions:
    layout = normalize_layout(layout_path, canvas_w, canvas_h)
    cfg = layout["indicators"]["fit_cadence_text"]
    min_dim = min(canvas_w, canvas_h)
    size_px = s(cfg["size"], canvas_w)
    chart_w = size_px
    chart_h = max(40, int(chart_w * 0.4))
    ss = 1  # AMD path uses ss=1

    print(f"\n[{res_name}] canvas={canvas_w}x{canvas_h}  chart={chart_w}x{chart_h}")

    # Reproduce the _build_chart_bg logic
    out_w, out_h = chart_w, chart_h
    width = chart_w * ss
    height = chart_h * ss

    axis_bottom_margin_est = int(max(6, height * 0.20)) * ss
    
    # label_font_size from chart.py → label_fs_px = 0 (not set)
    # _build_chart_bg internal formula:
    plot_h_est = max(1, height - 4 * ss - axis_bottom_margin_est)
    label_fs = int(max(7, min(width, height) * 0.13) * ss)
    label_fs = max(6, min(label_fs, max(6, plot_h_est // 2)))

    print(f"  label_fs={label_fs}")

    # Load REAL font
    font_axis = load_font(font_path, label_fs)

    img_tmp = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw_tmp = ImageDraw.Draw(img_tmp)

    label_100 = "100%"
    bbox = draw_tmp.textbbox((0, 0), label_100, font=font_axis)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]

    axis_bottom_margin = axis_bottom_margin_est
    plot_y2 = height - axis_bottom_margin

    needed = 5 + th  # space needed below plot_y2 for X labels
    space_available = height - plot_y2  # = axis_bottom_margin
    x_label_bottom = plot_y2 + needed

    print(f"  label '100%': tw={tw}, th={th}")
    print(f"  axis_bottom_margin={axis_bottom_margin}, plot_y2={plot_y2}")
    print(f"  x-label needs {needed}px below plot_y2, available={space_available}px")
    print(f"  x-label bottom in chart_img: {x_label_bottom}  (img height={height})")
    overflow_internal = x_label_bottom - height
    print(f"  overflow in chart_img: {overflow_internal:+d}px  {'<< CLIPPED INTERNALLY!' if overflow_internal > 0 else 'OK'}")

    # Final visual position on frame
    # margin_top from chart.py:
    fs_val = cfg.get("font_size") if "font_size" in cfg else cfg.get("size", 0.02)
    fs = max(8, s(fs_val, min_dim))
    margin_top = fs + 8  # label is set

    # final_h = chart_h + margin_top + 4
    final_h = chart_h + margin_top + 4
    logical_cy = s(cfg["y"], canvas_h)

    # center_y = logical_cy, paste_y = round(center_y - final_h/2)
    paste_y = int(round(logical_cy - final_h / 2.0))
    final_bottom = paste_y + final_h
    
    # Global position of x-label bottom
    # bg_img is pasted at (4, margin_top) in final_img
    # x-label bottom in final_img = margin_top + x_label_bottom
    x_label_global_bottom = paste_y + margin_top + x_label_bottom

    print(f"  fs={fs}, margin_top={margin_top}, final_h={final_h}")
    print(f"  paste_y={paste_y}, final_bottom={final_bottom}, frame_h={canvas_h}")
    print(f"  final_img overflow: {final_bottom - canvas_h:+d}px  {'<< CLIPPED' if final_bottom > canvas_h else 'OK'}")
    print(f"  x-label global bottom: {x_label_global_bottom}")
    x_overflow = x_label_global_bottom - canvas_h
    print(f"  x-label global overflow: {x_overflow:+d}px  {'<< X-LABELS CLIPPED!' if x_overflow > 0 else 'OK'}")
