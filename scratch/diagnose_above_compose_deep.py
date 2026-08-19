import sys
import time
import statistics
from pathlib import Path

root = Path("c:/_DEV/TeleM")
sys.path.insert(0, str(root))
sys.path.insert(0, str(root / "src"))

from PIL import Image, ImageDraw, ImageFont
from src.indicators.compositor import compose_overlay
from src.gui.layout_manager import normalize_layout
from src.ffmpeg.amd_native_exporter import _ordered_map_layout_parts
from scratch.measure_current_builder_baseline import setup_telemetry
from src.telemetry_precompute import build_telemetry_cache
from src.indicators.frame_data import build_active_fit_field_plan
from src.ffmpeg.worker_cache import _resolve_cache_value, init_worker
from src.indicators.helpers import s, load_font, parse_hex_color

root = Path("c:/_DEV/TeleM")
layout_raw = normalize_layout(root / "def_layout.json", 3840, 2160)
below_layout, map_above_layout, after_keys = _ordered_map_layout_parts(layout_raw)

tm = setup_telemetry("GX030120.MP4", "Popoludniowa_jazda_na_rowerze_solar_battery.fit")
fit_field_plan = build_active_fit_field_plan(layout_raw, (tm.fit_data or {}).keys())

init_worker(
    video_width=3840, video_height=2160, font_path="assets/Roboto-Bold.ttf",
    layout=layout_raw, field_samples=tm.fit_data or {},
    fit_data=tm.fit_data, gps_track=tm.get_gps_track_for_source("fit"),
    start_dt_utc=tm.start_dt_utc, tz_offset_hours=2.0,
    speed_samples=tm.speed_samples or [], track_samples=tm.track_samples or [],
    alt_samples=tm.alt_samples or [], target_fps=29.97,
)

cache = build_telemetry_cache(
    layout=layout_raw, base_dt=tm.start_dt_utc, tz_offset_hours=2.0,
    start_dt_utc=tm.start_dt_utc, speed_samples=tm.speed_samples or [],
    track_samples=tm.track_samples or [], alt_samples=tm.alt_samples or [],
    fit_data=tm.fit_data, chart_data={}, resolve_cache_value=_resolve_cache_value,
    fit_field_plan=fit_field_plan, total_frames=1131, target_fps=29.97,
)

print(f"ABOVE indicators in layout: {list(map_above_layout.get('indicators', {}).keys())}")

# 1. Profile detailed subtimers for 300 frames
subtimes = {
    "above_canvas_prepare": [],
    "above_indicator_dispatch": [],
    "above_text_layout": [],
    "above_font_lookup": [],
    "above_textbbox": [],
    "above_text_raster": [],
    "above_rotate": [],
    "above_shadow_outline": [],
    "above_paste": [],
    "above_bbox_tracking": [],
    "above_compose_total": [],
}

# Indicator tracking
ind_stats = {}
for k in map_above_layout.get("indicators", {}).keys():
    ind_stats[k] = {
        "text_history": [],
        "render_times": [],
    }

font_path = "assets/Roboto-Bold.ttf"
canvas_w, canvas_h = 3840, 2160

for f_idx in range(300):
    f_rec = cache.lookup(f_idx)
    
    t_tot_start = time.perf_counter()
    
    # a. Canvas prepare (allocating 3840x2160 RGBA)
    t0 = time.perf_counter()
    img = Image.new("RGBA", (canvas_w, canvas_h), (0, 0, 0, 0))
    t_canvas = (time.perf_counter() - t0) * 1000.0
    subtimes["above_canvas_prepare"].append(t_canvas)
    
    _bboxes = {}
    
    t_dispatch_tot = 0.0
    t_font_tot = 0.0
    t_bbox_tot = 0.0
    t_raster_tot = 0.0
    t_rotate_tot = 0.0
    t_shadow_tot = 0.0
    t_paste_tot = 0.0
    t_tracking_tot = 0.0
    t_layout_tot = 0.0
    
    for key, ind_cfg in map_above_layout.get("indicators", {}).items():
        if not ind_cfg or not ind_cfg.get("enabled", True):
            continue
            
        t_d0 = time.perf_counter()
        # lookup value
        extra_ind = f_rec.get("extra_indicators", {})
        known = extra_ind.get(key)
        val = known[0] if known else None
        unit = known[1] if known else ind_cfg.get("unit", "")
        label = known[2] if known else ind_cfg.get("label", key)
        t_dispatch_tot += (time.perf_counter() - t_d0) * 1000.0
        
        if val is None:
            ind_stats[key]["text_history"].append(None)
            continue
            
        # text formatting
        t_l0 = time.perf_counter()
        decimals = int(ind_cfg.get("decimals", 0))
        val_str = f"{val:.{decimals}f}"
        show_units = ind_cfg.get("show_units", True)
        if show_units and unit:
            txt = f"{label}: {val_str} {unit}" if label else f"{val_str} {unit}"
        elif label:
            txt = f"{label}: {val_str}"
        else:
            txt = val_str
        t_layout_tot += (time.perf_counter() - t_l0) * 1000.0
        
        ind_stats[key]["text_history"].append(txt)
        
        t_ind_render_start = time.perf_counter()
        
        # font lookup
        t_f0 = time.perf_counter()
        min_dim = min(canvas_w, canvas_h)
        fs_val = ind_cfg.get("font_size") if "font_size" in ind_cfg else ind_cfg.get("size", 0.02)
        fs = max(8, s(fs_val, min_dim))
        outline_raw = int(map_above_layout.get("global", {}).get("text_outline", 3))
        outline = max(0, int(round(outline_raw * min_dim / 1000)))
        font = load_font(font_path, fs)
        t_font_tot += (time.perf_counter() - t_f0) * 1000.0
        
        # textbbox
        t_b0 = time.perf_counter()
        text_color = parse_hex_color(ind_cfg.get("text_color", "#FFFFFF")) or (255, 255, 255)
        txt_w = int(font.getlength(txt) + outline * 4)
        t_bbox_tot += (time.perf_counter() - t_b0) * 1000.0
        
        # raster
        t_r0 = time.perf_counter()
        tmp = Image.new("RGBA", (txt_w, int(fs * 2)), (0, 0, 0, 0))
        draw = ImageDraw.Draw(tmp)
        t_shadow_start = time.perf_counter()
        draw.text(
            (outline, 0), txt, font=font,
            fill=(text_color[0], text_color[1], text_color[2], 255),
            stroke_width=outline, stroke_fill=(0, 0, 0, 255),
        )
        t_shadow_tot += (time.perf_counter() - t_shadow_start) * 1000.0
        bbox = tmp.getbbox()
        cropped = tmp.crop(bbox) if bbox else None
        t_raster_tot += (time.perf_counter() - t_r0) * 1000.0
        
        if cropped:
            # rotate
            t_rot0 = time.perf_counter()
            rotation = int(ind_cfg.get("rotation", 0)) % 360
            res = cropped
            if rotation == 90:
                res = res.transpose(Image.Transpose.ROTATE_90)
            elif rotation == 180:
                res = res.transpose(Image.Transpose.ROTATE_180)
            elif rotation == 270:
                res = res.transpose(Image.Transpose.ROTATE_270)
            t_rotate_tot += (time.perf_counter() - t_rot0) * 1000.0
            
            # paste
            t_p0 = time.perf_counter()
            px_x = s(ind_cfg.get("x", 0.0), canvas_w)
            px_y = s(ind_cfg.get("y", 0.0), canvas_h)
            if rotation in (90, 270):
                center_x = px_x + cropped.height // 2
                center_y = px_y + cropped.width // 2
            else:
                center_x = px_x + cropped.width // 2
                center_y = px_y + cropped.height // 2
            
            paste_x = int(round(center_x - res.width / 2))
            paste_y = int(round(center_y - res.height / 2))
            img.alpha_composite(res, (paste_x, paste_y))
            t_paste_tot += (time.perf_counter() - t_p0) * 1000.0
            
            # bbox tracking
            t_trk0 = time.perf_counter()
            _bboxes[key] = (paste_x, paste_y, res.width, res.height)
            t_tracking_tot += (time.perf_counter() - t_trk0) * 1000.0
            
        ind_stats[key]["render_times"].append((time.perf_counter() - t_ind_render_start) * 1000.0)
        
    t_tot_ms = (time.perf_counter() - t_tot_start) * 1000.0
    subtimes["above_indicator_dispatch"].append(t_dispatch_tot)
    subtimes["above_text_layout"].append(t_layout_tot)
    subtimes["above_font_lookup"].append(t_font_tot)
    subtimes["above_textbbox"].append(t_bbox_tot)
    subtimes["above_text_raster"].append(t_raster_tot - t_shadow_tot)
    subtimes["above_shadow_outline"].append(t_shadow_tot)
    subtimes["above_rotate"].append(t_rotate_tot)
    subtimes["above_paste"].append(t_paste_tot)
    subtimes["above_bbox_tracking"].append(t_tracking_tot)
    subtimes["above_compose_total"].append(t_tot_ms)

print("\n=== SUBTIMER BREAKDOWN OF ABOVE_COMPOSE (median ms) ===")
sum_sub = 0.0
for k, vals in subtimes.items():
    if k == "above_compose_total":
        continue
    med = statistics.median(vals)
    sum_sub += med
    print(f"  {k:30s}: {med:6.3f} ms")

tot_med = statistics.median(subtimes["above_compose_total"])
other_med = max(0.0, tot_med - sum_sub)
residual_pct = (other_med / tot_med) * 100.0 if tot_med > 0 else 0.0
print(f"  {'above_other':30s}: {other_med:6.3f} ms")
print(f"  {'TOTAL':30s}: {tot_med:6.3f} ms (Residual: {residual_pct:.2f}%)")

print("\n=== ABOVE INDICATOR INVENTORY ===")
print(f"{'Indicator Name':28s} | {'Form':6s} | {'Source':6s} | {'Unchanged %':11s} | {'Med Render (ms)':15s} | {'Example Text':30s}")
print("-" * 110)
for k, cfg in map_above_layout.get("indicators", {}).items():
    hist = ind_stats[k]["text_history"]
    r_times = ind_stats[k]["render_times"]
    
    # calc unchanged %
    unchanged_count = sum(1 for i in range(1, len(hist)) if hist[i] == hist[i-1] and hist[i] is not None)
    total_valid = sum(1 for x in hist if x is not None)
    unchanged_pct = (unchanged_count / max(1, total_valid - 1)) * 100.0 if total_valid > 1 else 100.0
    
    med_t = statistics.median(r_times) if r_times else 0.0
    sample_txt = str(hist[0] if hist else "None")[:28]
    
    form = cfg.get("form", "text")
    src = cfg.get("source", "fit")
    print(f"{k:28s} | {form:6s} | {src:6s} | {unchanged_pct:10.1f}% | {med_t:15.3f} | {sample_txt:30s}")
