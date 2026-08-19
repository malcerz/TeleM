"""
Diagnose three bboxes for chart indicators across resolutions.

A. LOGICAL WIDGET BBOX: from layout x, y, size (center-anchored)
B. LOCAL RENDER BBOX: actual final_img/final_static dimensions
C. FINAL VISUAL BBOX: local raster placed on output frame
"""
import sys, math
from pathlib import Path

root = Path("c:/_DEV/TeleM")
sys.path.insert(0, str(root))
sys.path.insert(0, str(root / "src"))

from src.gui.layout_manager import normalize_layout
from src.indicators.helpers import s
from src.indicators.dispatcher import render_value_indicator
from src.indicators.chart_utils import _build_chart_bg
from src.indicators.helpers import load_font
from PIL import Image, ImageDraw

layout_path = root / "def_layout.json"
font_path = "assets/Roboto-Bold.ttf"

resolutions = [
    (3840, 2160, "4K"),
    (1920, 1080, "1080p"),
    (1280, 720, "720p"),
    (854, 480, "480p"),
]

print("=" * 80)
print("CHART WIDGET BBOX DIAGNOSTIC — Three-Layer Analysis")
print("=" * 80)

for canvas_w, canvas_h, res_name in resolutions:
    layout = normalize_layout(layout_path, canvas_w, canvas_h)
    print(f"\n{'='*60}")
    print(f"[{res_name}] Canvas: {canvas_w}x{canvas_h}")
    print(f"{'='*60}")

    for key in ["fit_cadence_text", "fit_heart_rate_text"]:
        cfg = layout["indicators"][key]
        label_name = "Cadence" if "cadence" in key else "Heart Rate"
        unit_name = "rpm" if "cadence" in key else "BPM"

        # === A. LOGICAL WIDGET BBOX from layout ===
        x_pct = cfg["x"]  # percent of canvas_w
        y_pct = cfg["y"]  # percent of canvas_h
        logical_cx = s(x_pct, canvas_w)
        logical_cy = s(y_pct, canvas_h)

        # size in chart.py: size_px = s(cfg["size"], canvas_w)
        size_px = s(cfg["size"], canvas_w)
        # chart_w = size_px, chart_h = max(40, int(chart_w * 0.4))
        chart_w = size_px
        chart_h = max(40, int(chart_w * 0.4))

        # === B. LOCAL RENDER BBOX ===
        # final_img dimensions in _render_chart_indicator:
        # margin_top = fs + 8 if label else 0
        # final_h = chart_h + margin_top + 4
        # final_w = chart_w + 8
        min_dim = min(canvas_w, canvas_h)
        outline_raw = int(layout["global"].get("text_outline", 3))
        outline = max(0, int(round(outline_raw * min_dim / 1000)))
        fs_val = cfg.get("font_size") if "font_size" in cfg else cfg.get("size", 0.02)
        fs = max(8, s(fs_val, min_dim))
        label_str = label_name  # label is set

        margin_top = fs + 8 if label_str else 0
        final_w = chart_w + 8
        final_h = chart_h + margin_top + 4

        # === C. FINAL VISUAL BBOX ===
        # In compositor.py: center_x = rx, center_y = ry (non-text form)
        # paste_x = round(center_x - disp_w/2)
        # paste_y = round(center_y - disp_h/2)
        center_x = logical_cx
        center_y = logical_cy
        paste_x = int(round(center_x - final_w / 2.0))
        paste_y = int(round(center_y - final_h / 2.0))
        final_right = paste_x + final_w
        final_bottom = paste_y + final_h

        # Also compute actual rendered size via render_value_indicator
        img, rx, ry, _ = render_value_indicator(
            canvas_w=canvas_w, canvas_h=canvas_h,
            layout=layout, font_path=font_path,
            key=key, value=85.0, unit=unit_name, label=label_name,
            cfg_override=cfg, history_data=[60.0, 80.0, 90.0],
        )
        actual_final_w = img.width
        actual_final_h = img.height
        actual_center_x = rx
        actual_center_y = ry
        actual_paste_x = int(round(actual_center_x - actual_final_w / 2.0))
        actual_paste_y = int(round(actual_center_y - actual_final_h / 2.0))
        actual_final_right = actual_paste_x + actual_final_w
        actual_final_bottom = actual_paste_y + actual_final_h

        overflow_bottom = actual_final_bottom - canvas_h

        print(f"\n--- {key} ({label_name}) ---")
        print(f"  Layout: x={x_pct}%, y={y_pct}%, size={cfg['size']}%")
        print(f"")
        print(f"  A. LOGICAL CENTER: ({logical_cx}, {logical_cy})")
        print(f"")
        print(f"  B. LOCAL RENDER BBOX:")
        print(f"     chart_w={chart_w}, chart_h={chart_h}")
        print(f"     fs={fs}, margin_top={margin_top}")
        print(f"     final_img: {final_w}x{final_h}  (actual: {actual_final_w}x{actual_final_h})")
        print(f"")
        print(f"  C. FINAL VISUAL BBOX (actual render):")
        print(f"     center=({actual_center_x}, {actual_center_y})")
        print(f"     paste=({actual_paste_x}, {actual_paste_y})")
        print(f"     right={actual_final_right}, bottom={actual_final_bottom}")
        print(f"     overflow_bottom = {actual_final_bottom} - {canvas_h} = {overflow_bottom:+d} px  {'<< CLIPPED' if overflow_bottom > 0 else 'OK'}")

        # X axis label global positions
        # X labels are inside bg_img at y positions: plot_y2 + 5 .. plot_y2 + 5 + label_h
        # bg_img is pasted at (4, margin_top) in final_img
        # final_img is placed at (paste_y + margin_top ... )
        # Global Y of X-label bottom = paste_y + margin_top + plot_y2 + 5 + label_h_approx
        # Rough: plot_y2 = chart_h - axis_bottom_margin; axis_bottom_margin ~ chart_h * 0.20
        axis_bottom_margin_est = int(max(6, chart_h * 0.20))
        plot_y2_approx = chart_h - axis_bottom_margin_est
        xlabels_ty = margin_top + plot_y2_approx + 5  # local in final_img
        xlabels_bottom_local = xlabels_ty + 14  # approx text height + outline
        xlabels_global_top = actual_paste_y + xlabels_ty
        xlabels_global_bottom = actual_paste_y + xlabels_bottom_local
        print(f"")
        print(f"  X-axis labels (approx):")
        print(f"     local ty ~ {xlabels_ty}, bottom ~ {xlabels_bottom_local}")
        print(f"     global top ~ {xlabels_global_top}, bottom ~ {xlabels_global_bottom}")
        print(f"     x-label visible in frame: {'YES' if xlabels_global_bottom <= canvas_h else 'NO (clipped by ' + str(xlabels_global_bottom - canvas_h) + 'px)'}")
