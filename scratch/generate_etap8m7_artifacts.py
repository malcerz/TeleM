"""
Generate real full-frame test artifacts and bbox measurements for ETAP 8M.7.
"""
import sys, os
from pathlib import Path
from PIL import Image, ImageDraw

root = Path("c:/_DEV/TeleM")
sys.path.insert(0, str(root))
sys.path.insert(0, str(root / "src"))

from src.gui.layout_manager import normalize_layout, resolve_font_path
from src.indicators.helpers import s, load_font
from src.indicators.dispatcher import render_value_indicator
from src.indicators.compositor import compose_overlay

layout_path = root / "def_layout.json"
font_path = resolve_font_path("Arial")

out_dir = root / "Raporty/etap8m7_artifacts"
out_dir.mkdir(parents=True, exist_ok=True)

resolutions = [
    (3840, 2160, "4K"),
    (1920, 1080, "1080p"),
    (1280, 720, "720p"),
    (854, 480, "480p"),
]

# Generate synthetic realistic telemetry data
import math
history_cad = [60.0 + 40.0 * math.sin(i / 30.0) for i in range(300)]
history_hr = [120.0 + 35.0 * math.sin(i / 40.0) for i in range(300)]

print("="*70)
print("ETAP 8M.7 - FULL FRAME BBOX MEASUREMENTS")
print("="*70)

for canvas_w, canvas_h, res_name in resolutions:
    layout = normalize_layout(layout_path, canvas_w, canvas_h)
    
    # 1. Measure Cadence & HR bboxes
    print(f"\n--- RESOLUTION: {res_name} ({canvas_w}x{canvas_h}) ---")
    
    for key, label, unit, val, hist in [
        ("fit_cadence_text", "Cadence", "rpm", 95.0, history_cad),
        ("fit_heart_rate_text", "Heart Rate", "BPM", 145.0, history_hr),
    ]:
        cfg = layout["indicators"][key]
        img, rx, ry, _ = render_value_indicator(
            canvas_w=canvas_w, canvas_h=canvas_h,
            layout=layout, font_path=font_path,
            key=key, value=val, unit=unit, label=label,
            cfg_override=cfg, history_data=hist,
        )
        assert img is not None, f"Failed to render {key}"
        
        local_w, local_h = img.size
        final_left = int(round(rx - local_w / 2.0))
        final_top = int(round(ry - local_h / 2.0))
        final_right = final_left + local_w
        final_bottom = final_top + local_h
        overflow = final_bottom - canvas_h
        
        print(f"\n  Indicator: {key} ({label})")
        print(f"    A. Logical Widget BBox: x={cfg['x']}% ({s(cfg['x'], canvas_w)}px), y={cfg['y']}% ({s(cfg['y'], canvas_h)}px), size={cfg['size']}%")
        print(f"    B. Local Render BBox:   width={local_w}px, height={local_h}px")
        print(f"    C. Final Visual BBox:   left={final_left}, top={final_top}, right={final_right}, bottom={final_bottom}")
        print(f"       Canvas Height:       {canvas_h}px")
        print(f"       Bottom Overflow:     {overflow}px (final_bottom - canvas_h)")
        print(f"       Bottom Margin Gap:   {canvas_h - final_bottom}px inside canvas")

        # Global text bboxes for X-axis labels
        fs = max(10, int(s(cfg.get("font_size", cfg.get("size", 0.02)), canvas_h)))
        margin_top = fs + 8 if label else 0
        chart_w = s(cfg["size"], canvas_w)
        chart_h = max(40, int(chart_w * 0.4))
        
        # Calculate X labels global Y
        # From chart_utils: label_fs is calculated
        plot_h_est = max(1, chart_h - 4 - int(max(6, chart_h * 0.20)))
        label_fs = int(max(7, min(chart_w, chart_h) * 0.13))
        label_fs = max(6, min(label_fs, max(6, plot_h_est // 2)))
        font_axis = load_font(font_path, label_fs) if font_path else None
        
        draw_temp = ImageDraw.Draw(img)
        x_labels = ["0%", "25%", "50%", "75%", "100%"]
        max_th = 0
        for xl in x_labels:
            if font_axis:
                tb = draw_temp.textbbox((0, 0), xl, font=font_axis)
                max_th = max(max_th, tb[3] - tb[1])
            else:
                max_th = max(max_th, 10)
        
        axis_bottom_margin_est = int(max(6, chart_h * 0.20))
        needed_bottom_margin = int(math.ceil(5 + max_th + 2))
        axis_bottom_margin = max(axis_bottom_margin_est, needed_bottom_margin)
        plot_y2 = chart_h - axis_bottom_margin
        
        global_x_label_top = final_top + margin_top + plot_y2 + 5
        global_x_label_bottom = global_x_label_top + max_th
        print(f"    D. Global X Labels:     text_top={global_x_label_top}px, text_bottom={global_x_label_bottom}px (frame margin={canvas_h - global_x_label_bottom}px)")
        
        # Global Title & Value
        global_title_top = final_top
        global_title_bottom = final_top + fs
        print(f"    E. Global Title/Value:  title_top={global_title_top}px, title_bottom={global_title_bottom}px")

    # 2. Render Full Frame (Preview & Final)
    # Preview frame:
    preview_bg = Image.new("RGBA", (canvas_w, canvas_h), (20, 24, 30, 255))
    bboxes_preview = {}
    frame_preview = compose_overlay(
        canvas_w=canvas_w, canvas_h=canvas_h,
        layout=layout, font_path=font_path,
        date_text="19.08.2026",
        time_text="11:00:00",
        speed_value=32.5,
        distance_m=12400.0,
        cad_value=95.0,
        hr_value=145.0,
        alt_value=250.0,
        _bboxes=bboxes_preview,
        chart_data={
            "fit_cadence_text": history_cad,
            "fit_heart_rate_text": history_hr,
        },
        reuse_canvas=False,
    )
    # Paste overlay on preview background
    preview_full = Image.alpha_composite(preview_bg, frame_preview)
    
    # Draw a 1px boundary line at bottom of canvas to visualize full frame edge
    draw_p = ImageDraw.Draw(preview_full)
    draw_p.line([(0, canvas_h - 1), (canvas_w - 1, canvas_h - 1)], fill=(0, 255, 0, 255), width=1)
    
    # Final / AMD frame (same CPU compose path with GPU split/capture verification)
    final_bg = Image.new("RGBA", (canvas_w, canvas_h), (15, 18, 22, 255))
    gpu_capture = {}
    bboxes_final = {}
    frame_final_raw = compose_overlay(
        canvas_w=canvas_w, canvas_h=canvas_h,
        layout=layout, font_path=font_path,
        date_text="19.08.2026",
        time_text="11:00:00",
        speed_value=32.5,
        distance_m=12400.0,
        cad_value=95.0,
        hr_value=145.0,
        alt_value=250.0,
        _bboxes=bboxes_final,
        gpu_capture_keys={"fit_cadence_text", "fit_heart_rate_text"},
        gpu_capture=gpu_capture,
        split_chart_keys={"fit_cadence_text", "fit_heart_rate_text"},
        chart_data={
            "fit_cadence_text": history_cad,
            "fit_heart_rate_text": history_hr,
        },
        reuse_canvas=False,
    )
    # Simulate GPU compositing: blend static and dynamic tiles
    gpu_composited = frame_final_raw.copy()
    for ckey, cdata in gpu_capture.items():
        bx, by, bw, bh = cdata["bbox"]
        static_img = cdata["static"]
        gpu_composited.paste(static_img, (bx, by), static_img)
        # Paste value tile
        vt = cdata["value_tile"]
        vl = cdata["value_local"]
        if vt:
            gpu_composited.paste(vt, (bx + vl[0], by + vl[1]), vt)
        # Paste cursor tile
        ct = cdata["cursor_tile"]
        cl = cdata["cursor_local"]
        if ct:
            gpu_composited.paste(ct, (bx + cl[0], by + cl[1]), ct)
            
    final_full = Image.alpha_composite(final_bg, gpu_composited)
    draw_f = ImageDraw.Draw(final_full)
    draw_f.line([(0, canvas_h - 1), (canvas_w - 1, canvas_h - 1)], fill=(0, 255, 0, 255), width=1)

    # Save artifacts for 720p, 480p, etc.
    p_path = out_dir / f"{res_name.lower()}_preview_full.png"
    f_path = out_dir / f"{res_name.lower()}_final_full.png"
    preview_full.save(str(p_path))
    final_full.save(str(f_path))
    print(f"  Artifacts saved:")
    print(f"    - {p_path}")
    print(f"    - {f_path}")

print("\nDone generating artifacts.")
