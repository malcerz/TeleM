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
from src.indicators.helpers import load_font, s
from src.indicators.rotated_paste import rotated_paste
from src.indicators.time_block import render_time_block
from src.indicators.time_display import render_time_display


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
) -> Image.Image:
    """Compose the complete HUD overlay image from all indicators.

    Each indicator is rendered according to its layout config and blended
    onto a transparent RGBA canvas.

    Args:
        canvas_w, canvas_h: Output image dimensions.
        layout: Full HUD layout dict.
        font_path: Path to TrueType font.
        date_text, time_text: Formatted date/time strings.
        speed_value, distance_m, alt_value: Primary telemetry values.
        indicator_values: Optional per-indicator value overrides (metres for dist).
        _bboxes: Optional dict to populate with indicator bounding boxes.
        chart_data: Optional dict of chart history {key: [values]}.
        current_position: 0.0-1.0 playback position for chart cursors.
        extra_indicators: Optional dict of dynamically discovered indicators
            {key: (value, unit, label)} (e.g. FIT fields).

    Returns:
        RGBA PIL.Image with all indicators composited.
    """
    img = Image.new("RGBA", (canvas_w, canvas_h), (0, 0, 0, 0))
    if _bboxes is None:
        _bboxes = {}

    # Time block
    if "time_block" in layout.get("indicators", {}):
        tb, tbx, tby = render_time_block(canvas_w, canvas_h, layout, font_path, date_text, time_text)
        if tb:
            tb_rotation = layout["indicators"]["time_block"].get("rotation", 0)
            rotated_paste(img, tb, tbx + tb.width // 2, tby + tb.height // 2, tb_rotation)
            if tb_rotation == 90:
                _bboxes["time_block"] = (
                    int(tbx - tb.height // 2),
                    int(tby - tb.width // 2),
                    tb.height,
                    tb.width,
                )
            else:
                _bboxes["time_block"] = (
                    int(tbx - tb.width // 2),
                    int(tby - tb.height // 2),
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
            rotated_paste(img, td, tdx + td.width // 2, tdy + td.height // 2, td_rotation)
            if td_rotation == 90:
                _bboxes["time_display"] = (
                    int(tdx - td.height // 2),
                    int(tdy - td.width // 2),
                    td.height,
                    td.width,
                )
            else:
                _bboxes["time_display"] = (
                    int(tdx - td.width // 2),
                    int(tdy - td.height // 2),
                    td.width,
                    td.height,
                )

    if indicator_values is None:
        indicator_values = {}

    # All indicators to render
    indicator_defs = [
        ("speed_visual", speed_value, "km/h", ""),
        ("speed_text", speed_value, "km/h", ""),
        ("dist_visual", distance_m / 1000.0, "km", ""),
        ("dist_text", distance_m / 1000.0, "km", ""),
        ("alt_visual", alt_value, "m", "Alt"),
        ("alt_text", alt_value, "m", "Alt"),
        ("iso_text", iso_value if iso_value is not None else 0, "ISO", "ISO"),
        ("exposure_text", exposure_value if exposure_value is not None else 0, "", "Exp"),
        ("temp_text", temp_value if temp_value is not None else 0, "C", "Temp"),
        ("power_text", power_value if power_value is not None else 0, "W", "Moc"),
        ("atemp_text", atemp_value if atemp_value is not None else 0, "\u00b0C", "ATemp"),
        ("hr_text", hr_value if hr_value is not None else 0, "BPM", "HR"),
        ("cad_text", cad_value if cad_value is not None else 0, "RPM", "Cad"),
        ("battery_text", battery_value if battery_value is not None else 0, "%", "Bat"),
        ("track_map", 0.0, "", "Mapa"),
    ]

    for key, default_value, unit, default_label in indicator_defs:
        # Skip missing or disabled indicators early
        ind_cfg_orig = layout["indicators"].get(key)
        if ind_cfg_orig is None or (not ind_cfg_orig.get("enabled", True)):
            continue
        if key in indicator_values:
            raw = indicator_values[key]
            if key in ("dist_visual", "dist_text"):
                value = raw / 1000.0
            else:
                value = raw
        else:
            value = float(default_value)

        current_cfg = layout["indicators"][key].copy()

        if key == "dist_visual" and max_distance_m is not None:
            current_cfg["max_val"] = max(current_cfg["min_val"] + 0.001, max_distance_m / 1000.0)

        if key == "speed_visual" and max_speed_kmh is not None:
            rounded = math.ceil(max_speed_kmh / 10.0) * 10
            current_cfg["max_val"] = max(current_cfg.get("min_val", 0) + 0.001, rounded)

        if key in ("alt_visual", "alt_text") and min_alt is not None and max_alt is not None:
            current_cfg["min_val"] = min_alt
            current_cfg["max_val"] = max(min_alt + 1.0, max_alt)

        label = current_cfg.get("label", default_label)

        # Build formatted value
        if key == "iso_text":
            fv = f"{int(value)}"
        elif key == "exposure_text":
            fv = f"1/{int(value)}" if value and int(value) > 0 else ""
        elif key == "temp_text":
            fv = f"{int(value)}\u00b0C"
        elif key == "power_text":
            fv = f"{int(value)}W"
        elif key == "atemp_text":
            fv = f"{int(value)}\u00b0C"
        elif key == "hr_text":
            fv = f"{int(value)} BPM"
        elif key == "cad_text":
            fv = f"{int(value)} RPM"
        elif key == "battery_text":
            fv = f"{int(value)}%"
        else:
            fv = None

        chart_vals = None
        if chart_data and key in chart_data:
            chart_vals = chart_data[key]

        # Determine supersampling factor (global or per-indicator)
        global_ss = 1 if fast_preview else layout.get("global", {}).get("antialiasing", 1)
        ss = 1 if fast_preview else current_cfg.get("supersample", global_ss)
        res, rx, ry, extra = render_value_indicator(
            canvas_w,
            canvas_h,
            layout,
            font_path,
            key,
            value,
            unit,
            label,
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
            rotation = layout["indicators"][key].get("rotation", 0)
            if layout["indicators"][key].get("form", "text") == "text":
                if rotation == 90:
                    rx = rx + res.height // 2
                else:
                    rx = rx + res.width // 2
            rotated_paste(img, res, rx, ry, rotation)

            if rotation == 90:
                _bboxes[key] = (
                    int(ry - res.height // 2),
                    int(rx - res.width // 2),
                    res.height,
                    res.width,
                )
            elif rotation == 180:
                _bboxes[key] = (
                    int(rx - res.width // 2),
                    int(ry - res.height // 2),
                    res.width,
                    res.height,
                )
            elif rotation == 270:
                _bboxes[key] = (
                    int(ry - res.width // 2),
                    int(rx - res.height // 2),
                    res.height,
                    res.width,
                )
            else:
                _bboxes[key] = (
                    int(rx - res.width // 2),
                    int(ry - res.height // 2),
                    res.width,
                    res.height,
                )

            draw = ImageDraw.Draw(img)
            cfg = current_cfg
            fs = max(10, int(s(cfg["font_size"], canvas_h)))
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
                    text_x = int(rx + res.height + 8 + ox)
                    text_y = int(ry + res.width / 2 - text_h / 2 + oy)
                else:
                    text_x = int(rx + extra["dot_x"] - text_w / 2 + ox)
                    text_y = int(ry + extra["dot_y"] - text_h - 8 + oy)
                draw.text(
                    (text_x, text_y),
                    text,
                    font=font,
                    fill=(255, 255, 255, 255),
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
                    left_x = int(rx - res.width // 2 + extra["x1"] - left_w - 8 + rox)
                    left_y = int(ry + res.width - left_h / 2 + roy)
                    draw.text(
                        (left_x, left_y),
                        left_text,
                        font=font,
                        fill=(220, 220, 220, 255),
                        stroke_width=outline,
                        stroke_fill=(0, 0, 0, 255),
                    )
                    if right_text:
                        right_x = int(rx - res.width // 2 + extra["x2"] + rox)
                        right_y = int(ry - right_h / 2 + roy - rspreadx)
                        draw.text(
                            (right_x, right_y),
                            right_text,
                            font=font,
                            fill=(220, 220, 220, 255),
                            stroke_width=outline,
                            stroke_fill=(0, 0, 0, 255),
                        )
                else:
                    left_y = int(ry + extra["by"] + 4 + roy)
                    left_x = int(rx - res.width // 2 + extra["x1"] + rox)
                    draw.text(
                        (left_x, left_y),
                        left_text,
                        font=font,
                        fill=(220, 220, 220, 255),
                        stroke_width=outline,
                        stroke_fill=(0, 0, 0, 255),
                    )
                    if right_text:
                        right_x = int(rx - res.width // 2 + extra["x2"] - right_w + rox + rspreadx)
                        draw.text(
                            (right_x, left_y),
                            right_text,
                            font=font,
                            fill=(220, 220, 220, 255),
                            stroke_width=outline,
                            stroke_fill=(0, 0, 0, 255),
                        )

    # ── Extra indicators (dynamically discovered, e.g. FIT fields) ──
    rendered_keys = {k for k, _, _, _ in indicator_defs}
    rendered_keys.add("time_block")  # already rendered above, skip fallback
    rendered_keys.add("time_display")  # already rendered above, skip fallback
    if extra_indicators:
        for key, (value, unit, label) in extra_indicators.items():
            if key not in layout["indicators"]:
                continue
            current_cfg = layout["indicators"][key].copy()
            if not current_cfg.get("enabled", True):
                continue
            label = current_cfg.get("label", label)

            fv = f"{value:.1f} {unit}" if unit else f"{value:.1f}"
            chart_vals = chart_data.get(key) if chart_data else None
            res, rx, ry, _extra = render_value_indicator(
                canvas_w, canvas_h, layout, font_path,
                key, value, unit, label,
                cfg_override=current_cfg,
                formatted_val=fv,
                history_data=chart_vals,
                current_position=current_position,
            )
            if res:
                rotation = current_cfg.get("rotation", 0)
                if current_cfg.get("form", "text") == "text":
                    if rotation == 90:
                        rx = rx + res.height // 2
                    else:
                        rx = rx + res.width // 2
                rotated_paste(img, res, rx, ry, rotation)
                _bboxes[key] = (int(rx - res.width // 2), int(ry - res.height // 2), res.width, res.height)
            rendered_keys.add(key)

    # ── FALLBACK: wszystkie pozostałe wskaźniki z layoutu ──────────────
    for key in list(layout.get("indicators", {}).keys()):
        if key in rendered_keys:
            continue
        current_cfg = layout["indicators"][key].copy()
        if not current_cfg.get("enabled", True):
            continue
        val = 0.0
        unit = current_cfg.get("unit", "")
        label = current_cfg.get("label", key)
        if extra_indicators and key in extra_indicators:
            val, unit, label = extra_indicators[key]
        fv = f"{val:.1f} {unit}" if unit else f"{val:.1f}"
        chart_vals = chart_data.get(key) if chart_data else None
        res, rx, ry, _extra = render_value_indicator(
            canvas_w, canvas_h, layout, font_path,
            key, val, unit, label,
            cfg_override=current_cfg,
            formatted_val=fv,
            history_data=chart_vals,
            current_position=current_position,
        )
        if res:
            rotation = current_cfg.get("rotation", 0)
            if current_cfg.get("form", "text") == "text":
                if rotation == 90:
                    rx = rx + res.height // 2
                else:
                    rx = rx + res.width // 2
            rotated_paste(img, res, rx, ry, rotation)
            _bboxes[key] = (int(rx - res.width // 2), int(ry - res.height // 2), res.width, res.height)

    # Custom texts – use resolution-scaled outline
    ct_outline = max(0, int(round(
        int(layout.get("global", {}).get("text_outline", 3)) * min(canvas_w, canvas_h) / 1000
    )))
    for ct_cfg in layout.get("custom_texts", []):
        ct_res, ctx, cty = render_custom_text(canvas_w, canvas_h, font_path, ct_cfg, stroke_width=ct_outline)
        if ct_res:
            ct_rotation = int(ct_cfg.get("rotation", 0))
            rotated_paste(img, ct_res, ctx, cty, ct_rotation)

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
) -> Image.Image:
    """Render a preview image: source frame with HUD overlay composited on top."""
    # Avoid a full-resolution copy if the image is already RGBA
    img = src_img if src_img.mode == "RGBA" else src_img.convert("RGBA")
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
        start_dt_utc=start_dt_utc,
        elapsed_seconds=elapsed_seconds,
        avg_speed_kmh=avg_speed_kmh,
        fast_preview=True,
    )
    img.alpha_composite(overlay)
    return img
