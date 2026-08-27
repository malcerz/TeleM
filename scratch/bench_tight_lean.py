import math
import sys
import time
import statistics
import json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import numpy as np
from PIL import Image, ImageDraw

from src.gui.telemetry_manager import TelemetryDataManager
from src.telemetry_processed_cache import read_processed_cache, apply_processed_cache
from src.indicators.frame_data import build_active_fit_field_plan
from src.indicators.helpers import load_font, s
from src.indicators.lean import (
    _draw_text_bounded_cached,
    _graphic_pivot,
    _load_lean_graphic,
    _rotate_paste_params,
    lean_angle,
    _BoundedStaticCache,
    _static_cache_key,
    _text_size,
    _draw_text_bounded,
)
from src.ffmpeg.worker_cache import init_worker
from src.telemetry_precompute import build_telemetry_cache

VIDEO = Path("Video/GX030120.MP4")
LAYOUT_PATH = Path("def_layout.json")
FRAMES = 300
FPS = 30000.0 / 1001.0
CANVAS_W, CANVAS_H = 3840, 2160

# We will measure REF vs CAND
def run_benchmark():
    layout = json.load(open(LAYOUT_PATH, encoding="utf-8"))
    cfg = layout["indicators"]["lean_indicator"]
    min_dim = min(CANVAS_W, CANVAS_H)
    outline_raw = int(layout.get("global", {}).get("text_outline", 3))
    outline = max(0, int(round(outline_raw * min_dim / 1000)))
    fs_val = cfg.get("font_size") if "font_size" in cfg else cfg.get("size", 0.02)
    fs = max(8, s(fs_val, min_dim))
    thickness = max(1, s(float(cfg.get("thickness", 1)), min_dim))
    size_px = s(cfg.get("size", 0.1), CANVAS_W)
    
    # Pre-fetch telemetry values
    tm = TelemetryDataManager()
    processed = read_processed_cache(VIDEO)
    assert processed is not None
    apply_processed_cache(tm, processed)
    field_samples = {k: getattr(tm, k) for k in [
        "speed_samples", "track_samples", "alt_samples", "heading_samples",
        "gpx_heading_samples", "slope_samples", "gpx_slope_samples", "iso_samples",
        "exposure_samples", "temperature_samples", "accel_x_samples", "accel_y_samples",
        "accel_z_samples", "accel_magnitude_samples", "gyro_x_samples", "gyro_y_samples",
        "gyro_z_samples", "gyro_magnitude_samples",
    ]}
    fit_data = tm.fit_data or {}
    init_worker(
        video_width=CANVAS_W, video_height=CANVAS_H, font_path="",
        layout=layout, field_samples=field_samples,
        iso_samples=tm.iso_samples, exposure_samples=tm.exposure_samples,
        temperature_samples=tm.temperature_samples, fit_data=fit_data,
        gps_track=(tm.gps_track or []), start_dt_utc=tm.start_dt_utc,
        target_fps=FPS, total_overlay_frames=FRAMES,
    )
    cache = build_telemetry_cache(
        layout=layout, base_dt=tm.start_dt_utc, tz_offset_hours=2.0,
        start_dt_utc=tm.start_dt_utc, speed_samples=tm.speed_samples,
        track_samples=tm.track_samples, alt_samples=tm.alt_samples,
        iso_samples=tm.iso_samples, exposure_samples=tm.exposure_samples,
        temperature_samples=tm.temperature_samples, fit_data=fit_data,
        gps_track=tm.gps_track or [], chart_data={},
        resolve_cache_value=None, _range_cache={},
        fit_field_plan=build_active_fit_field_plan(layout, list(fit_data.keys())),
        total_frames=FRAMES, target_fps=FPS,
    )
    values = [cache.lookup(i)["extra_indicators"]["lean_indicator"][0] for i in range(FRAMES)]
    angles = [lean_angle(v, cfg) for v in values]
    
    # Common widget parameters
    font_path = "arial.ttf"
    ss = 1
    pad = 8 * ss
    g = max(32 * ss, int(size_px * ss))
    show_label = bool(cfg.get("show_label", True))
    show_value = bool(cfg.get("show_value", True))
    show_reference = bool(cfg.get("show_reference", True))
    show_ticks = bool(cfg.get("show_ticks", True))
    uppercase_title = bool(cfg.get("uppercase_title", True))
    decimals = max(0, int(cfg.get("decimals", 0)))
    max_angle = abs(float(cfg.get("max_angle", 30.0)))
    title_fs = max(8 * ss, int(round(float(cfg.get("title_font_scale", 1.0)) * fs * ss)))
    value_fs = max(8 * ss, int(round(float(cfg.get("value_font_scale", 0.9)) * fs * ss)))
    title_font = load_font(font_path, title_fs)
    value_font = load_font(font_path, value_fs)
    text_stroke = max(0, int(round(max(1, outline) * ss)))
    raw_title = str(cfg.get("title_text", "PRZECHYŁ")).strip()
    title = raw_title.upper() if uppercase_title else raw_title
    dummy = Image.new("RGBA", (16, 16), (0, 0, 0, 0))
    dd = ImageDraw.Draw(dummy)
    title_h = _text_size(dd, title, title_font, text_stroke)[1] if show_label and title else 0
    # Use representative value text for layout width
    val_sample = f"{angles[0]:+.{decimals}f}\u00b0" if show_value else ""
    value_w = _text_size(dd, val_sample, value_font, text_stroke)[0] if val_sample else 0
    value_h = _text_size(dd, val_sample, value_font, text_stroke)[1] if val_sample else 0
    title_gap = 5 * ss if title_h else 0
    value_gap = 4 * ss if value_h else 0
    ref_color = (255, 255, 255, int(255 * 0.55))
    tick_color = (255, 255, 255, int(255 * 0.35))
    raster_w = max(g + 2 * pad, value_w + 2 * pad, 2 * pad + 40)
    top = pad + title_h + title_gap
    center_y = top + g / 2.0
    raster_h = int(top + g + value_gap + value_h + pad)
    
    # Base cache
    base = Image.new("RGBA", (raster_w, raster_h), (0, 0, 0, 0))
    d = ImageDraw.Draw(base)
    cx = raster_w / 2.0
    if show_label and title:
        _draw_text_bounded(d, (raster_w / 2, pad), title, font=title_font, fill=(255, 255, 255, 255), stroke_width=text_stroke, stroke_fill=(0, 0, 0, 230), bounds=(raster_w, raster_h), anchor="ma")
    if show_reference:
        d.line((pad, center_y, raster_w - pad, center_y), fill=ref_color, width=max(1, int(round(1.4 * ss))))
    if show_ticks:
        step = 10.0
        tick_range = min(max_angle, 90.0)
        t = -tick_range
        while t <= tick_range + 1e-6:
            frac = max(-1.0, min(1.0, t / max(1.0, max_angle)))
            x = cx + frac * (g / 2.0 - 4 * ss)
            tl = (4 * ss) if abs(abs(t) - tick_range) < 1e-6 else (3 * ss)
            d.line((x, center_y - tl, x, center_y + tl), fill=tick_color, width=max(1, int(round(1.0 * ss))))
            t += step
            
    graphic = _load_lean_graphic(cfg, g)
    gw, gh = graphic.size
    pivot_px, pivot_py = _graphic_pivot(cfg, gw, gh)
    
    # Padded graphic source (cached!)
    pad_src_margin = 4
    padded_graphic = Image.new("RGBA", (gw + 2 * pad_src_margin, gh + 2 * pad_src_margin), (0, 0, 0, 0))
    padded_graphic.alpha_composite(graphic, (pad_src_margin, pad_src_margin))
    ppivot_px = pivot_px + pad_src_margin
    ppivot_py = pivot_py + pad_src_margin
    
    pad_ref, paste_x_ref, paste_y_ref, sx_ref, sy_ref = _rotate_paste_params(gw, gh, pivot_px, pivot_py, raster_w, center_y)
    px_ref = int(round(paste_x_ref))
    py_ref = int(round(paste_y_ref))
    gx_ref = int(round(pad_ref / 2.0 - pivot_px))
    gy_ref = int(round(pad_ref / 2.0 - pivot_py))
    
    # --- Measure CAND (Tight) ---
    cand_t_rot, cand_t_comp, cand_t_total, cand_sizes = [], [], [], []
    
    corners_rel = [
        (-pivot_px, -pivot_py),
        (gw - pivot_px, -pivot_py),
        (gw - pivot_px, gh - pivot_py),
        (-pivot_px, gh - pivot_py),
    ]
    
    for i in range(FRAMES):
        ang = angles[i]
        val_text = f"{ang:+.{decimals}f}\u00b0" if show_value else ""
        t0 = time.perf_counter()
        
        img = base.copy()
        
        # Tight rotate
        t_rot_0 = time.perf_counter()
        if abs(ang) < 1e-6:
            tight_img = None
            dest_x = px_ref + gx_ref
            dest_y = py_ref + gy_ref
            tw, th = gw, gh
        else:
            rad = -math.radians(ang)
            a_mat = round(math.cos(rad), 15)
            b_mat = round(math.sin(rad), 15)
            d_mat = round(-math.sin(rad), 15)
            e_mat = round(math.cos(rad), 15)
            
            rot_c = [
                (a_mat * xg_rel + d_mat * yg_rel + 309.0, b_mat * xg_rel + e_mat * yg_rel + 309.0)
                for xg_rel, yg_rel in corners_rel
            ]
            min_xd = min(c[0] for c in rot_c)
            max_xd = max(c[0] for c in rot_c)
            min_yd = min(c[1] for c in rot_c)
            max_yd = max(c[1] for c in rot_c)
            
            margin = 4
            xd0 = max(0, int(math.floor(min_xd)) - margin)
            yd0 = max(0, int(math.floor(min_yd)) - margin)
            xd1 = min(pad_ref, int(math.ceil(max_xd)) + margin)
            yd1 = min(pad_ref, int(math.ceil(max_yd)) + margin)
            
            tw = xd1 - xd0
            th = yd1 - yd0
            
            c_x = a_mat * (xd0 - 309.0) + b_mat * (yd0 - 309.0) + ppivot_px
            c_y = d_mat * (xd0 - 309.0) + e_mat * (yd0 - 309.0) + ppivot_py
            matrix = (a_mat, b_mat, c_x, d_mat, e_mat, c_y)
            
            tight_img = padded_graphic.transform(
                (tw, th),
                Image.Transform.AFFINE,
                matrix,
                resample=Image.Resampling.BICUBIC,
            )
            dest_x = px_ref + xd0
            dest_y = py_ref + yd0
            
        t_rot_1 = time.perf_counter()
        cand_t_rot.append((t_rot_1 - t_rot_0) * 1000)
        cand_sizes.append(tw * th)
        
        # Composite
        t_comp_0 = time.perf_counter()
        if tight_img is None:
            img.alpha_composite(graphic, (dest_x, dest_y))
        else:
            cx0 = max(0, dest_x)
            cy0 = max(0, dest_y)
            cx1 = min(raster_w, dest_x + tw)
            cy1 = min(raster_h, dest_y + th)
            if cx1 > cx0 and cy1 > cy0:
                if (cx0, cy0, cx1, cy1) == (dest_x, dest_y, dest_x + tw, dest_y + th):
                    img.alpha_composite(tight_img, (dest_x, dest_y))
                else:
                    cropped = tight_img.crop((cx0 - dest_x, cy0 - dest_y, cx1 - dest_x, cy1 - dest_y))
                    img.alpha_composite(cropped, (cx0, cy0))
        t_comp_1 = time.perf_counter()
        cand_t_comp.append((t_comp_1 - t_comp_0) * 1000)
        
        if val_text:
            _draw_text_bounded_cached(
                img, (raster_w / 2, top + g + value_gap), val_text,
                font=value_font, font_path=font_path, fill=(255, 255, 255, 255),
                stroke_width=text_stroke, stroke_fill=(0, 0, 0, 230),
                bounds=(raster_w, raster_h), anchor="ma",
            )
        t1 = time.perf_counter()
        cand_t_total.append((t1 - t0) * 1000)
        
    def p95(xs):
        s = sorted(xs)
        return s[min(len(s) - 1, int(round(0.95 * (len(s) - 1))))]
        
    print(f"CAND (TIGHT) over {FRAMES} frames:")
    print(f"  tight rotate:    AVG={statistics.fmean(cand_t_rot):7.3f} ms  MEDIAN={statistics.median(cand_t_rot):7.3f} ms  P95={p95(cand_t_rot):7.3f} ms")
    print(f"  tight composite: AVG={statistics.fmean(cand_t_comp):7.3f} ms  MEDIAN={statistics.median(cand_t_comp):7.3f} ms  P95={p95(cand_t_comp):7.3f} ms")
    print(f"  total lean call: AVG={statistics.fmean(cand_t_total):7.3f} ms  MEDIAN={statistics.median(cand_t_total):7.3f} ms  P95={p95(cand_t_total):7.3f} ms")
    print(f"  mean tight bbox area: {statistics.fmean(cand_sizes):.0f} px^2 ({100.0 * statistics.fmean(cand_sizes) / (618*618):.1f}% of 618x618)")

if __name__ == "__main__":
    run_benchmark()
