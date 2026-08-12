"""Composite overlay rendering — compose all indicators into a single RGBA image.

Extracted from ``overlay_renderer.py``.
"""

from __future__ import annotations

import math
from datetime import datetime
from typing import Any, Optional

try:
    from PIL import Image, ImageDraw
except ImportError:
    Image = None  # type: ignore
    ImageDraw = None  # type: ignore

from src.indicators.custom_text import render_custom_text
from src.indicators.dispatcher import render_value_indicator
from src.indicators.helpers import load_font, s, parse_hex_color
from src.indicators.rotated_paste import rotated_paste
from src.indicators.time_block import render_time_block
from src.indicators.time_display import render_time_display


import threading

_THREAD_CANVAS = threading.local()


def _get_reusable_canvas(canvas_w: int, canvas_h: int) -> tuple[Image.Image, dict[str, tuple[int, int, int, int]]]:
    if not hasattr(_THREAD_CANVAS, "cache"):
        _THREAD_CANVAS.cache = {}
    key = (canvas_w, canvas_h)
    if key not in _THREAD_CANVAS.cache:
        img = Image.new("RGBA", (canvas_w, canvas_h), (0, 0, 0, 0))
        prev_bboxes: dict[str, tuple[int, int, int, int]] = {}
        _THREAD_CANVAS.cache[key] = (img, prev_bboxes)
    return _THREAD_CANVAS.cache[key]


def compose_overlay(
    canvas_w: int,
    canvas_h: int,
    layout: dict[str, Any],
    font_path: str,
    date_text: str,
    time_text: str,
    speed_value: float,
    distance_m: float,
    max_distance_m: Optional[float] = None,
    alt_value: float = 0.0,
    min_alt: Optional[float] = None,
    max_alt: Optional[float] = None,
    iso_value: Optional[float] = None,
    exposure_value: Optional[float] = None,
    temp_value: Optional[float] = None,
    indicator_values: Optional[dict[str, float]] = None,
    max_speed_kmh: Optional[float] = None,
    power_value: Optional[float] = None,
    atemp_value: Optional[float] = None,
    hr_value: Optional[float] = None,
    cad_value: Optional[float] = None,
    battery_value: Optional[float] = None,
    _bboxes: Optional[dict[str, tuple[int, int, int, int]]] = None,
    chart_data: Optional[dict[str, list[float]]] = None,
    current_position: Optional[float] = None,
    extra_indicators: Optional[dict[str, tuple[float, str, str]]] = None,
    gps_track: Optional[list[tuple[Any, float, float]]] = None,
    target_dt: Optional[datetime] = None,
    start_dt_utc: Optional[datetime] = None,
    elapsed_seconds: float = 0.0,
    avg_speed_kmh: float = 0.0,
    fast_preview: bool = False,
    reuse_canvas: bool = True,
) -> Image.Image:
    """Compose the complete HUD overlay image from all indicators."""
    if reuse_canvas:
        img, prev_bboxes = _get_reusable_canvas(canvas_w, canvas_h)
        if prev_bboxes:
            pad = 40
            for bx, by, bw, bh in prev_bboxes.values():
                x1 = max(0, bx - pad)
                y1 = max(0, by - pad)
                x2 = min(canvas_w, bx + bw + pad)
                y2 = min(canvas_h, by + bh + pad)
                img.paste((0, 0, 0, 0), (x1, y1, x2, y2))
            prev_bboxes.clear()
        else:
            img.paste((0, 0, 0, 0), (0, 0, canvas_w, canvas_h))
    else:
        img = Image.new("RGBA", (canvas_w, canvas_h), (0, 0, 0, 0))
        prev_bboxes = None

    if _bboxes is None:
        _bboxes = {}

    # Time block
    if "time_block" in layout.get("indicators", {}):
        tb, tbx, tby = render_time_block(canvas_w, canvas_h, layout, font_path, date_text, time_text)
        if tb:
            tb_rotation = layout["indicators"]["time_block"].get("rotation", 0)
            # Treść jest wklejana środkiem w (cx, cy); pozycja layout x/y to lewy-górny róg.
            cx = tbx + tb.width // 2
            cy = tby + tb.height // 2
            rotated_paste(img, tb, cx, cy, tb_rotation)
            if tb_rotation in (90, 270):
                _bboxes["time_block"] = (
                    int(cx - tb.height // 2),
                    int(cy - tb.width // 2),
                    tb.height,
                    tb.width,
                )
            else:
                _bboxes["time_block"] = (
                    int(cx - tb.width // 2),
                    int(cy - tb.height // 2),
                    tb.width,
                    tb.height,
                )

    # Time display (multi-line info block)
    if "time_display" in layout.get("indicators", {}):
        td, tdx, tdy = render_time_display(
            canvas_w, canvas_h, layout, font_path,
            date_text, time_text, elapsed_seconds, avg_speed_kmh,
        )
        if td:
            td_rotation = layout["indicators"]["time_display"].get("rotation", 0)
            cx = tdx + td.width // 2
            cy = tdy + td.height // 2
            rotated_paste(img, td, cx, cy, td_rotation)
            if td_rotation in (90, 270):
                _bboxes["time_display"] = (
                    int(cx - td.height // 2),
                    int(cy - td.width // 2),
                    td.height,
                    td.width,
                )
            else:
                _bboxes["time_display"] = (
                    int(cx - td.width // 2),
                    int(cy - td.height // 2),
                    td.width,
                    td.height,
                )

    if indicator_values is None:
        indicator_values = {}

    # Map of all default built-in values
    known_vals: dict[str, tuple[float, str, str]] = {
        "speed_visual": (speed_value, "km/h", ""),
        "speed_text": (speed_value, "km/h", ""),
        "dist_visual": (distance_m / 1000.0, "km", ""),
        "dist_text": (distance_m / 1000.0, "km", ""),
        "alt_visual": (alt_value, "m", "Alt"),
        "alt_text": (alt_value, "m", "Alt"),
        "iso_text": (iso_value if iso_value is not None else 0.0, "ISO", "ISO"),
        "exposure_text": (exposure_value if exposure_value is not None else 0.0, "", "Exp"),
        "temp_text": (temp_value if temp_value is not None else 0.0, "\u00b0C", "Temp"),
        "power_text": (power_value if power_value is not None else 0.0, "W", "Moc"),
        "atemp_text": (atemp_value if atemp_value is not None else 0.0, "\u00b0C", "ATemp"),
        "hr_text": (hr_value if hr_value is not None else 0.0, "BPM", "HR"),
        "cad_text": (cad_value if cad_value is not None else 0.0, "RPM", "Cad"),
        "battery_text": (battery_value if battery_value is not None else 0.0, "%", "Bat"),
        "track_map": (0.0, "", "Mapa"),
    }

    # Overlay with extra indicators (e.g. FIT fields dynamically discovered)
    if extra_indicators:
        for k, v in extra_indicators.items():
            known_vals[k] = v

    # Apply per-indicator value overrides
    for k, raw in indicator_values.items():
        val = raw / 1000.0 if k in ("dist_visual", "dist_text") else raw
        if k in known_vals:
            _, u, l = known_vals[k]
            known_vals[k] = (val, u, l)
        else:
            known_vals[k] = (val, "", k)

    # Render ALL indicators configured in layout (GPMF, FIT, GPX, Custom)
    for key, ind_cfg in layout.get("indicators", {}).items():
        if key in ("time_block", "time_display"):
            continue
        if not ind_cfg or not ind_cfg.get("enabled", True):
            continue

        value, default_unit, default_label = known_vals.get(
            key, (0.0, ind_cfg.get("unit", ""), ind_cfg.get("label", key))
        )
        # An empty string in the layout must not suppress a sensible unit —
        # fall back to the default unit for the data source.
        unit = ind_cfg.get("unit") or default_unit
        label = ind_cfg.get("label", default_label)

        current_cfg = ind_cfg.copy()

        # Dynamic max/min range scaling for visual bars/gauges
        if key == "dist_visual" and max_distance_m is not None:
            current_cfg["max_val"] = max(current_cfg.get("min_val", 0) + 0.001, max_distance_m / 1000.0)
        elif key == "speed_visual" and max_speed_kmh is not None:
            rounded = math.ceil(max_speed_kmh / 10.0) * 10
            current_cfg["max_val"] = max(current_cfg.get("min_val", 0) + 0.001, rounded)
        elif key in ("alt_visual", "alt_text") and min_alt is not None and max_alt is not None:
            current_cfg["min_val"] = min_alt
            current_cfg["max_val"] = max(min_alt + 1.0, max_alt)

        # Formatting
        show_value = current_cfg.get("show_value", True)
        if not show_value:
            fv = ""
        else:
            default_decimals = 0 if key in ("iso_text", "exposure_text", "temp_text", "atemp_text", "power_text", "hr_text", "cad_text", "battery_text") or key.startswith("fit_") else 1
            decimals = int(current_cfg.get("decimals", default_decimals))

            if key == "exposure_text":
                val_str = f"1/{int(value)}" if value and int(value) > 0 else ""
            else:
                val_str = f"{value:.{decimals}f}"

            show_units = current_cfg.get("show_units", True)
            if show_units:
                if key in ("temp_text", "atemp_text"):
                    fv = f"{val_str}\u00b0C"
                elif key == "power_text":
                    fv = f"{val_str}W"
                elif key == "hr_text":
                    fv = f"{val_str} BPM"
                elif key == "cad_text":
                    fv = f"{val_str} RPM"
                elif key == "battery_text":
                    fv = f"{val_str}%"
                elif key == "iso_text":
                    fv = val_str
                else:
                    fv = f"{val_str} {unit}" if unit else val_str
            else:
                fv = val_str

        chart_vals = chart_data.get(key) if chart_data else None

        global_ss = 1 if fast_preview else layout.get("global", {}).get("antialiasing", 1)
        ss = 1 if fast_preview else current_cfg.get("supersample", global_ss)

        res, rx, ry, extra = render_value_indicator(
            canvas_w, canvas_h, layout, font_path,
            key, value, unit, label,
            cfg_override=current_cfg,
            formatted_val=fv,
            max_distance_m=max_distance_m,
            history_data=chart_vals,
            current_position=current_position,
            gps_track=gps_track,
            supersample=ss,
            target_dt=target_dt,
        )

        if res:
            rotation = int(current_cfg.get("rotation", 0))
            is_text = current_cfg.get("form", "text") == "text"

            if is_text:
                if rotation in (90, 270):
                    center_x = rx + res.height // 2
                    center_y = ry + res.width // 2
                else:
                    center_x = rx + res.width // 2
                    center_y = ry + res.height // 2
            else:
                center_x = rx
                center_y = ry

            rotated_paste(img, res, center_x, center_y, rotation)

            if rotation in (90, 270):
                bw, bh = res.height, res.width
            else:
                bw, bh = res.width, res.height

            _bboxes[key] = (int(center_x - bw // 2), int(center_y - bh // 2), int(bw), int(bh))

            # Extra text annotations / range labels
            draw = ImageDraw.Draw(img)
            cfg = current_cfg
            fs = max(10, int(s(cfg.get("font_size", cfg.get("size", 0.02)), canvas_h)))
            font = load_font(font_path, fs)
            outline = max(1, fs // 12)

            if extra and extra.get("show_value") and key != "dist_visual":
                text = extra["value_text"]
                bbox = draw.textbbox((0, 0), text, font=font)
                text_w = bbox[2] - bbox[0]
                text_h = bbox[3] - bbox[1]
                ox = int(round(cfg.get("text_offset_x", 0.0) * canvas_w))
                oy = int(round(cfg.get("text_offset_y", 0.0) * canvas_h))
                if rotation == 90:
                    text_x = int(center_x + res.height // 2 + 8 + ox)
                    text_y = int(center_y - text_h / 2 + oy)
                else:
                    text_x = int(center_x + extra["dot_x"] - res.width // 2 - text_w / 2 + ox)
                    text_y = int(center_y + extra["dot_y"] - res.height // 2 - text_h - 8 + oy)
                text_color = parse_hex_color(cfg.get("text_color", "#FFFFFF")) or (255, 255, 255)
                draw.text(
                    (text_x, text_y),
                    text,
                    font=font,
                    fill=(text_color[0], text_color[1], text_color[2], 255),
                    stroke_width=outline,
                    stroke_fill=(0, 0, 0, 255),
                )

            if extra and extra.get("show_range_labels"):
                left_text = extra.get("left_text", f"{cfg.get('min_val', 0):.0f}")
                right_text = extra.get("right_text", f"{cfg.get('max_val', 100):.0f}")
                rox = int(round(cfg.get("range_label_offset_x", 0.0) * canvas_w))
                roy = int(round(cfg.get("range_label_offset_y", 0.0) * canvas_h))
                rspreadx = int(round(cfg.get("range_label_spread_x", 0.0) * canvas_w))

                left_bbox = draw.textbbox((0, 0), left_text, font=font)
                left_w = left_bbox[2] - left_bbox[0]
                left_h = left_bbox[3] - left_bbox[1]
                if right_text:
                    right_bbox = draw.textbbox((0, 0), right_text, font=font)
                    right_w = right_bbox[2] - right_bbox[0]
                    right_h = right_bbox[3] - right_bbox[1]
                else:
                    right_w = right_h = 0

                if rotation == 90:
                    left_x = int(center_x - res.height // 2 + extra["x1"] - left_w - 8 + rox)
                    left_y = int(center_y + res.width // 2 - left_h / 2 + roy)
                    draw.text((left_x, left_y), left_text, font=font, fill=(220, 220, 220, 255), stroke_width=outline, stroke_fill=(0, 0, 0, 255))
                    if right_text:
                        right_x = int(center_x - res.height // 2 + extra["x2"] + rox)
                        right_y = int(center_y - res.width // 2 - right_h / 2 + roy - rspreadx)
                        draw.text((right_x, right_y), right_text, font=font, fill=(220, 220, 220, 255), stroke_width=outline, stroke_fill=(0, 0, 0, 255))
                else:
                    left_y = int(center_y - res.height // 2 + extra["by"] + 4 + roy)
                    left_x = int(center_x - res.width // 2 + extra["x1"] + rox)
                    draw.text((left_x, left_y), left_text, font=font, fill=(220, 220, 220, 255), stroke_width=outline, stroke_fill=(0, 0, 0, 255))
                    if right_text:
                        right_x = int(center_x - res.width // 2 + extra["x2"] - right_w + rox + rspreadx)
                        draw.text((right_x, left_y), right_text, font=font, fill=(220, 220, 220, 255), stroke_width=outline, stroke_fill=(0, 0, 0, 255))

    # Custom texts – use resolution-scaled outline
    ct_outline = max(0, int(round(
        int(layout.get("global", {}).get("text_outline", 3)) * min(canvas_w, canvas_h) / 1000
    )))
    for ct_cfg in layout.get("custom_texts", []):
        ct_res, ctx, cty = render_custom_text(canvas_w, canvas_h, font_path, ct_cfg, stroke_width=ct_outline)
        if ct_res:
            ct_rotation = int(ct_cfg.get("rotation", 0))
            rotated_paste(img, ct_res, ctx, cty, ct_rotation)

    if prev_bboxes is not None and _bboxes:
        prev_bboxes.update(_bboxes)

    return img


def render_preview(
    src_img: Image.Image,
    layout: dict[str, Any],
    font_path: str,
    date_text: str,
    time_text: str,
    speed_value: float,
    distance_m: float,
    max_distance_m: Optional[float] = None,
    alt_value: float = 0.0,
    min_alt: Optional[float] = None,
    max_alt: Optional[float] = None,
    iso_value: Optional[float] = None,
    exposure_value: Optional[float] = None,
    temp_value: Optional[float] = None,
    indicator_values: Optional[dict[str, float]] = None,
    max_speed_kmh: Optional[float] = None,
    power_value: Optional[float] = None,
    atemp_value: Optional[float] = None,
    hr_value: Optional[float] = None,
    cad_value: Optional[float] = None,
    battery_value: Optional[float] = None,
    _bboxes: Optional[dict[str, tuple[int, int, int, int]]] = None,
    chart_data: Optional[dict[str, list[float]]] = None,
    current_position: Optional[float] = None,
    extra_indicators: Optional[dict[str, tuple[float, str, str]]] = None,
    gps_track: Optional[list[tuple[Any, float, float]]] = None,
    target_dt: Optional[datetime] = None,
    start_dt_utc: Optional[datetime] = None,
    elapsed_seconds: float = 0.0,
    avg_speed_kmh: float = 0.0,
    inplace: bool = False,
) -> Image.Image:
    """Render a preview image: source frame with HUD overlay composited on top."""
    # Avoid a full-resolution copy if the image is already RGBA
    img = src_img if src_img.mode == "RGBA" else src_img.convert("RGBA")
    if not inplace:
        img = img.copy()
    w, h = img.size
    if _bboxes is None:
        _bboxes = {}
    overlay = compose_overlay(
        w,
        h,
        layout,
        font_path,
        date_text,
        time_text,
        speed_value,
        distance_m,
        max_distance_m,
        alt_value,
        min_alt,
        max_alt,
        iso_value,
        exposure_value,
        temp_value,
        indicator_values=indicator_values,
        max_speed_kmh=max_speed_kmh,
        power_value=power_value,
        atemp_value=atemp_value,
        hr_value=hr_value,
        cad_value=cad_value,
        battery_value=battery_value,
        _bboxes=_bboxes,
        chart_data=chart_data,
        current_position=current_position,
        extra_indicators=extra_indicators,
        gps_track=gps_track,
        target_dt=target_dt,
        start_dt_utc=start_dt_utc,
        elapsed_seconds=elapsed_seconds,
        avg_speed_kmh=avg_speed_kmh,
        fast_preview=True,
    )
    # Bypass OpenCL to check CPU alpha_composite performance
    img.alpha_composite(overlay)
    return img
