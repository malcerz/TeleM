"""
Generate actual rendered chart images for visual inspection.
Compare preview vs AMD (same CPU render path since AMD uses same render).
"""
import sys, os
from pathlib import Path
from PIL import Image

root = Path("c:/_DEV/TeleM")
sys.path.insert(0, str(root))
sys.path.insert(0, str(root / "src"))

from src.gui.layout_manager import normalize_layout, resolve_font_path
from src.indicators.helpers import s
from src.indicators.dispatcher import render_value_indicator

layout_path = root / "def_layout.json"
font_path = resolve_font_path("Arial")

# Create output dir
out_dir = root / "Raporty/etap8m7_artifacts"
out_dir.mkdir(parents=True, exist_ok=True)

resolutions = [
    (3840, 2160, "4K"),
    (1920, 1080, "1080p"),
    (1280, 720, "720p"),
    (854, 480, "480p"),
]

# Create a fake but realistic history data set
def make_history(n=500, min_v=50, max_v=180):
    import math
    vals = [min_v + (max_v - min_v) * (0.5 + 0.4 * math.sin(i / 50.0)) for i in range(n)]
    return vals

history = make_history()

for canvas_w, canvas_h, res_name in resolutions:
    layout = normalize_layout(layout_path, canvas_w, canvas_h)
    cfg_cad = layout["indicators"]["fit_cadence_text"]
    cfg_hr = layout["indicators"]["fit_heart_rate_text"]

    # Full black frame
    frame = Image.new("RGBA", (canvas_w, canvas_h), (30, 30, 30, 255))

    for key, cfg, label, unit in [
        ("fit_cadence_text", cfg_cad, "Cadence", "rpm"),
        ("fit_heart_rate_text", cfg_hr, "Heart Rate", "BPM"),
    ]:
        img, rx, ry, _ = render_value_indicator(
            canvas_w=canvas_w, canvas_h=canvas_h,
            layout=layout, font_path=font_path,
            key=key, value=95.0, unit=unit, label=label,
            cfg_override=cfg, history_data=history,
        )
        if img is None:
            print(f"[{res_name}] {key}: render returned None")
            continue

        # Composite onto frame (center-anchored)
        px = int(round(rx - img.width / 2.0))
        py = int(round(ry - img.height / 2.0))
        frame.paste(img, (px, py), img)
        print(f"[{res_name}] {key}: img={img.size} paste=({px},{py}) bottom={py+img.height}/{canvas_h}")

    # Draw frame bottom edge as red line for visualization
    from PIL import ImageDraw
    draw = ImageDraw.Draw(frame)
    draw.line([(0, canvas_h - 1), (canvas_w - 1, canvas_h - 1)], fill=(255, 0, 0, 255), width=3)

    out_path = out_dir / f"chart_preview_{res_name}.png"
    # Scale down 4K to 1080p for easier viewing
    if canvas_w > 1920:
        frame = frame.resize((canvas_w // 2, canvas_h // 2), Image.LANCZOS)
    frame.save(str(out_path))
    print(f"  Saved: {out_path}")
