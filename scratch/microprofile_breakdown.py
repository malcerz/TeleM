import sys
import json
import time
from pathlib import Path
from collections import defaultdict
import statistics

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.gui.telemetry_manager import TelemetryDataManager
from src.indicators.frame_data import prepare_overlay_frame_data
import src.indicators.compositor as compositor
import src.indicators.chart as chart
import src.indicators.chart_utils as chart_utils
from src.telemetry_extract import (
    extract_speed_samples, extract_altitude_samples, extract_track_samples,
    extract_iso_samples, extract_exposure_samples, extract_temperature_samples,
    ensure_records_list, extract_gps_track,
    smooth_speed_samples, interpolate_value, get_rotation_from_metadata,
    get_container_rotation, find_metadata_json, load_json_with_fallback,
    smooth_speed_values, extract_accelerometer_samples, extract_gyroscope_samples,
)

root = Path(__file__).resolve().parents[1]
video_path = root / "Video" / "GX010115.MP4"
json_path = root / "Video" / "GX010115.json"
fit_path = root / "Video" / "Jazda_na_rowerze_w_porze_lunchu.fit"
layout_path = root / "presets" / "cycling_dashboard_v10.json"

with open(layout_path, "r", encoding="utf-8") as f:
    layout = json.load(f)

telemetry = TelemetryDataManager(
    extract_speed_fn=extract_speed_samples,
    extract_altitude_fn=extract_altitude_samples,
    extract_track_fn=extract_track_samples,
    extract_iso_fn=extract_iso_samples,
    extract_exposure_fn=extract_exposure_samples,
    extract_temperature_fn=extract_temperature_samples,
    smooth_fn=smooth_speed_samples,
    interpolate_fn=interpolate_value,
    get_rotation_meta_fn=get_rotation_from_metadata,
    get_container_rotation_fn=get_container_rotation,
    find_meta_json_fn=find_metadata_json,
    find_meta_json_write_fn=lambda p: p.with_suffix(".json"),
    load_telemetry_fn=lambda *a: None,
    ensure_records_fn=ensure_records_list,
    load_json_fallback_fn=load_json_with_fallback,
    write_records_fn=lambda p, r: None,
    extract_samples_exiftool_fn=lambda f: [],
    extract_altitude_exiftool_fn=lambda f: [],
    extract_gps_track_fn=extract_gps_track,
    find_gps_anchor_fn=lambda r: None,
    smooth_values_fn=smooth_speed_values,
    extract_accelerometer_fn=extract_accelerometer_samples,
    extract_gyroscope_fn=extract_gyroscope_samples,
)

with open(json_path, "r", encoding="utf-8") as f:
    meta = json.load(f)
records = ensure_records_list(meta)
telemetry.load_gpmf_records(records)
telemetry.load_gps_track(records)
telemetry.load_fit(video_path, telemetry.start_dt_utc, manual_path=fit_path)

timings = defaultdict(lambda: defaultdict(list))

from src.indicators.helpers import _STATIC_CACHE, _static_cache_key, load_font, parse_hex_color
from PIL import ImageDraw

def detailed_render(
    canvas_w, canvas_h, layout, font_path, key, value, unit, label,
    cfg, min_dim, outline, fs, font, val_min, val_max, ticks, thickness, size_px, ss,
    history_data=None, current_position=None, formatted_val=None,
    split_mode=False, target_dt=None,
):
    t_start = time.perf_counter()

    # Step 1: history prep & timestamps
    t0 = time.perf_counter()
    time_labels = None
    chart_vals = None
    timestamps = None
    if isinstance(history_data, dict):
        chart_vals = history_data.get("values", [])
        time_labels = history_data.get("time_labels")
        timestamps = history_data.get("timestamps")
    elif isinstance(history_data, list):
        chart_vals = history_data
        timestamps = getattr(history_data, "timestamps", None)

    if not chart_vals:
        chart_vals = [value, value]

    chart_w = size_px
    chart_h = max(40, int(chart_w * 0.4))
    t1 = time.perf_counter()
    timings[key]["1_history_prep"].append((t1 - t0) * 1000.0)

    # Step 2: get_history_chart_background
    t0 = time.perf_counter()
    line_clr = chart.get_chart_color(key)
    graph_kwargs = dict(
        line_color=line_clr, line_thickness=thickness,
        fill_alpha=cfg.get("fill_alpha", 50),
        fill_color=parse_hex_color(cfg.get("fill_color")),
        show_axes=cfg.get("show_axes", True),
        grid_color=parse_hex_color(cfg.get("grid_color")),
        time_labels=time_labels,
        value_labels=None, supersample=ss,
        custom_min_val=val_min, custom_max_val=val_max,
        label_count=ticks, label_units=True, unit=unit,
        show_average=cfg.get("show_average", False), label_font_size=chart.s(1.0, min_dim),
        font_path=font_path,
    )
    chart_start_dt = getattr(history_data, "chart_start_dt", None)
    chart_end_dt = getattr(history_data, "chart_end_dt", None)
    t_start_chart = chart_start_dt or (timestamps[0] if timestamps else None)
    t_end_chart = chart_end_dt or (timestamps[-1] if timestamps else None)
    
    bg_img, points, plot_y1, plot_y2, calc_thickness, bg_key = (
        chart_utils.get_history_chart_background(chart_vals, chart_w, chart_h, **graph_kwargs)
    )
    t1 = time.perf_counter()
    timings[key]["2_bg_cache_lookup"].append((t1 - t0) * 1000.0)

    # Step 3: cursor calculation & bisect
    t0 = time.perf_counter()
    ci = None
    pos = None
    align_start = t_start_chart
    align_end = t_end_chart
    if timestamps and len(timestamps) >= 1 and target_dt is not None and t_start_chart is not None and t_end_chart is not None:
        sample_tz = timestamps[0].tzinfo
        aligned_target = target_dt
        if sample_tz is None and target_dt.tzinfo is not None:
            aligned_target = target_dt.replace(tzinfo=None)
        elif sample_tz is not None and target_dt.tzinfo is None:
            from datetime import timezone
            aligned_target = target_dt.replace(tzinfo=timezone.utc)

        if sample_tz is None:
            if align_start.tzinfo is not None:
                align_start = align_start.replace(tzinfo=None)
            if align_end.tzinfo is not None:
                align_end = align_end.replace(tzinfo=None)
        else:
            if align_start.tzinfo is None:
                align_start = align_start.replace(tzinfo=timezone.utc)
            if align_end.tzinfo is None:
                align_end = align_end.replace(tzinfo=timezone.utc)

        if align_end > align_start:
            pos = (aligned_target - align_start).total_seconds() / (align_end - align_start).total_seconds()
            pos = max(0.0, min(1.0, pos))

    if pos is not None and points:
        if (
            timestamps
            and len(timestamps) == len(points)
            and align_start is not None
            and align_end is not None
            and align_end > align_start
        ):
            norm_0 = max(0.0, min(1.0, (timestamps[0] - align_start).total_seconds() / (align_end - align_start).total_seconds()))
            norm_last = max(0.0, min(1.0, (timestamps[-1] - align_start).total_seconds() / (align_end - align_start).total_seconds()))
            if norm_last > norm_0:
                plot_w_span = (points[-1][0] - points[0][0]) / (norm_last - norm_0)
                plot_x1_base = points[0][0] - norm_0 * plot_w_span
                cursor_x = plot_x1_base + pos * plot_w_span
            else:
                cursor_x = points[0][0]
        else:
            cursor_x = points[0][0] + pos * (points[-1][0] - points[0][0])

        if timestamps and len(timestamps) == len(points) and target_dt is not None:
            from bisect import bisect_right
            idx = bisect_right(timestamps, aligned_target) - 1
            if idx < 0:
                py = points[0][1]
            elif idx >= len(points) - 1:
                py = points[-1][1]
            else:
                dt0, dt1 = timestamps[idx], timestamps[idx + 1]
                dt_span = (dt1 - dt0).total_seconds()
                gap_limit = 5.0
                if dt_span > 0 and chart_vals[idx] is not None and chart_vals[idx + 1] is not None:
                    frac = max(0.0, min(1.0, (aligned_target - dt0).total_seconds() / dt_span))
                    py = points[idx][1] + frac * (points[idx + 1][1] - points[idx][1])
                else:
                    py = points[idx][1]
        else:
            idx = int(round(pos * (len(points) - 1)))
            idx = max(0, min(len(points) - 1, idx))
            py = points[idx][1]

        if py is not None:
            ci = (cursor_x, py)
    t1 = time.perf_counter()
    timings[key]["3_cursor_calc_bisect"].append((t1 - t0) * 1000.0)

    # Step 4: header & static cache
    t0 = time.perf_counter()
    margin_top = fs + 8 + outline if label else 0
    final_h = chart_h + margin_top + 4
    text_color_rgb = parse_hex_color(cfg.get("text_color", "#FFFFFF")) or (255, 255, 255)
    text_color = (text_color_rgb[0], text_color_rgb[1], text_color_rgb[2], 255)
    tox = int(round(cfg.get("text_offset_x", 0.0) * chart_w))
    toy = int(round(cfg.get("text_offset_y", 0.0) * chart_h))
    v_str = formatted_val if formatted_val is not None else (f"{value:.1f} {unit}".strip() if value is not None else f"-- {unit}".strip())

    hdr_key = _static_cache_key("chart_hdr", chart_w + 8, final_h, label, font_path, fs, outline, text_color, tox, toy)
    hdr_img = _STATIC_CACHE.get(hdr_key)
    if hdr_img is None:
        hdr_img = chart.Image.new("RGBA", (chart_w + 8, final_h), (0, 0, 0, 0))
        if label:
            if font is None:
                font = load_font(font_path, max(8, int(fs)))
            d_hdr = ImageDraw.Draw(hdr_img)
            d_hdr.text((4 + tox, outline + toy), label, font=font, fill=text_color, stroke_width=outline, stroke_fill=(0, 0, 0, 255))
        _STATIC_CACHE[hdr_key] = hdr_img

    final_key = ("final_static_chart", bg_key, hdr_key, chart_w + 8, final_h, margin_top)
    final_static = chart._FINAL_STATIC_CHART_CACHE.get(final_key)
    if final_static is None:
        final_static = hdr_img.copy()
        final_static.paste(bg_img, (4, margin_top), bg_img)
        chart._FINAL_STATIC_CHART_CACHE[final_key] = final_static
    t1 = time.perf_counter()
    timings[key]["4_header_static_cache"].append((t1 - t0) * 1000.0)

    # Step 5: final_static.copy()
    t0 = time.perf_counter()
    final_img = final_static.copy()
    t1 = time.perf_counter()
    timings[key]["5_final_static_copy"].append((t1 - t0) * 1000.0)

    # Step 6: _draw_post_paste_cursor
    t0 = time.perf_counter()
    chart._draw_post_paste_cursor(
        final_img, points, ci, plot_y1, plot_y2, calc_thickness,
        (255, 255, 255), line_clr, 4, margin_top, chart_w, chart_h,
    )
    t1 = time.perf_counter()
    timings[key]["6_draw_cursor"].append((t1 - t0) * 1000.0)

    # Step 7: dynamic text (masks + draw.bitmap)
    t0 = time.perf_counter()
    draw = ImageDraw.Draw(final_img)
    if v_str:
        masks = chart._render_value_text_masks(v_str, font, text_color, outline)
        if masks is not None:
            stroke_mask, fill_mask, sl, st, vw = masks
            text_x = chart_w - vw + tox + sl
            text_y = toy + st
            draw.bitmap((text_x, text_y), stroke_mask, fill=(0, 0, 0, 255))
            draw.bitmap((text_x, text_y), fill_mask, fill=text_color)
    t1 = time.perf_counter()
    timings[key]["7_dynamic_text_draw"].append((t1 - t0) * 1000.0)

    t_end = time.perf_counter()
    timings[key]["total"].append((t_end - t_start) * 1000.0)

    _final_w = chart_w + 8
    _min_ry = int(math.ceil(final_h / 2.0)) if "math" in globals() else final_h // 2
    return final_img, 0, 0, None

import math
import src.indicators.dispatcher as dispatcher
chart._render_chart_indicator = detailed_render
compositor._render_chart_indicator = detailed_render
dispatcher._render_chart_indicator = detailed_render

from datetime import timedelta
start_dt = telemetry.start_dt_utc

# Warmup 10 frames
for i in range(10):
    dt = start_dt + timedelta(seconds=i / 60.0)
    kwargs = prepare_overlay_frame_data(
        target_dt=dt,
        start_dt_utc=start_dt,
        tz_offset_hours=2.0,
        layout=layout,
        speed_samples=telemetry.speed_samples,
        track_samples=telemetry.track_samples,
        alt_samples=telemetry.alt_samples,
        iso_samples=telemetry.iso_samples,
        exposure_samples=telemetry.exposure_samples,
        temperature_samples=telemetry.temperature_samples,
        fit_data=telemetry.fit_data,
        gps_track=telemetry.get_gps_track_for_source("fit"),
        resolve_cache_value=lambda k, src, d, ind=None: telemetry.resolve_value(k, d, source=src),
    )
    compositor.compose_overlay(1280, 720, layout, "", reuse_canvas="above", **kwargs)

timings.clear()

# Measure steady-state frames 11-120
for i in range(10, 120):
    dt = start_dt + timedelta(seconds=i / 60.0)
    kwargs = prepare_overlay_frame_data(
        target_dt=dt,
        start_dt_utc=start_dt,
        tz_offset_hours=2.0,
        layout=layout,
        speed_samples=telemetry.speed_samples,
        track_samples=telemetry.track_samples,
        alt_samples=telemetry.alt_samples,
        iso_samples=telemetry.iso_samples,
        exposure_samples=telemetry.exposure_samples,
        temperature_samples=telemetry.temperature_samples,
        fit_data=telemetry.fit_data,
        gps_track=telemetry.get_gps_track_for_source("fit"),
        resolve_cache_value=lambda k, src, d, ind=None: telemetry.resolve_value(k, d, source=src),
    )
    compositor.compose_overlay(1280, 720, layout, "", reuse_canvas="above", **kwargs)

print("\n" + "="*85)
print("MICROPROFILE BREAKDOWN (Frames 11-120 Steady State)")
print("="*85)

for k in ["fit_heart_rate_text", "fit_cadence_text"]:
    print(f"\n### {k} ###")
    for phase, vals in sorted(timings[k].items()):
        mean_v = statistics.fmean(vals)
        med_v = statistics.median(vals)
        print(f"  {phase:<25} | mean: {mean_v:6.3f} ms | median: {med_v:6.3f} ms | min: {min(vals):6.3f} ms | max: {max(vals):6.3f} ms")
