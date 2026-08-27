"""Composite overlay rendering — compose all indicators into a single RGBA image.

Extracted from ``overlay_renderer.py``.
"""

from __future__ import annotations

import math
import time
import copy
from datetime import datetime
from typing import Any, Optional

try:
    from PIL import Image, ImageDraw
except ImportError:
    Image = None  # type: ignore
    ImageDraw = None  # type: ignore

from src.indicators.chart import ChartSplit
from src.indicators.custom_text import render_custom_text
from src.indicators.dispatcher import render_value_indicator
from src.indicators.helpers import indicator_font_path, load_font, s, parse_hex_color
from src.indicators.rotated_paste import rotated_paste
from src.indicators.time_display import render_time_display
from src.indicators.profiling import get_overlay_profiler, indicator_scope


import threading

_THREAD_CANVAS = threading.local()

# Legacy indicator keys that have been removed from the program (ETAP 4A.1).
# Old saved projects may still contain them; they are skipped (not rendered)
# so such projects load and render without crashing.
_REMOVED_LEGACY_KEYS = frozenset({"time_block"})


def _is_legacy_vertical_ruler(cfg: dict[str, Any]) -> bool:
    """Identify the old horizontal-ruler-plus-90-degree layout shape."""
    return (
        cfg.get("form", "text") in ("bar", "segment_bar")
        and str(cfg.get("bar_style", "ruler")).strip().lower() == "ruler"
        and "orientation" not in cfg
        and int(cfg.get("rotation", 0) or 0) % 360 in (90, 270)
    )


def _effective_indicator_cfg(key: str, cfg: dict[str, Any]) -> dict[str, Any]:
    """Normalize any legacy Ruler rotation at runtime only.

    Older presets represented a vertical ruler as a horizontal ruler with
    ``rotation=90``. The current vertical-ruler contract keeps text horizontal,
    so migrate this semantic shape without mutating the saved layout.
    """
    effective = cfg.copy()
    if (
        _is_legacy_vertical_ruler(effective)
    ):
        effective["orientation"] = "vertical"
        effective["rotation"] = 0
    return effective


def normalize_layout_for_save(layout: dict[str, Any]) -> dict[str, Any]:
    """Persist modern orientation fields instead of the legacy rotation hack."""
    saved = copy.deepcopy(layout)
    for cfg in saved.get("indicators", {}).values():
        if isinstance(cfg, dict) and _is_legacy_vertical_ruler(cfg):
            cfg["orientation"] = "vertical"
            cfg["rotation"] = 0
    return saved

def _get_reusable_canvas(
    canvas_w: int, canvas_h: int, canvas_type: str = "below"
) -> tuple[Image.Image, dict[str, tuple[int, int, int, int]], dict[str, Any]]:
    if not hasattr(_THREAD_CANVAS, "below_cache"):
        _THREAD_CANVAS.below_cache = {}
        _THREAD_CANVAS.above_cache = {}
    
    storage = _THREAD_CANVAS.above_cache if canvas_type == "above" else _THREAD_CANVAS.below_cache
    key = (canvas_w, canvas_h)
    if key not in storage:
        img = Image.new("RGBA", (canvas_w, canvas_h), (0, 0, 0, 0))
        prev_bboxes: dict[str, tuple[int, int, int, int]] = {}
        state = {"is_clean": True}
        storage[key] = (img, prev_bboxes, state)
    return storage[key]


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
    # ETAP 10R: optional additive channel for the alpha-tight bounding box of
    # each pasted widget in absolute canvas coordinates (``{key: {"rect":
    # (x, y, w, h) | None, "clipped": bool}}``).  When None (the default) the
    # behaviour is 100% unchanged; when provided, composite_final records the
    # alpha-tight bbox (the canonical ``alpha != 0`` bbox, identical to what
    # the AMD SCAN path re-derives via ``getchannel("A").getbbox()``) for
    # every widget pasted into the canvas.  This is the data source for the
    # AMD_ABOVE_DIRTY_MODE=EXACT fast dirty-bbox path.
    _tight_bboxes: Optional[dict[str, Any]] = None,
    chart_data: Optional[dict[str, list[float]]] = None,
    current_position: Optional[float] = None,
    extra_indicators: Optional[dict[str, tuple[float, str, str]]] = None,
    gps_track: Optional[list[tuple[Any, float, float]]] = None,
    target_dt: Optional[datetime] = None,
    start_dt_utc: Optional[datetime] = None,
    elapsed_seconds: float = 0.0,
    avg_speed_kmh: float = 0.0,
    fast_preview: bool = False,
    reuse_canvas: bool | str = True,
    # ETAP 5J: GPU final compositing for the cadence/HR charts.  When a key is
    # in *gpu_capture_keys*, the chart widget is still rendered on the CPU with
    # the exact same renderer (raw RGBA byte-identical), but it is NOT pasted
    # into the Pillow HUD canvas.  Instead its raw RGBA + bbox are handed back
    # through *gpu_capture* so the exporter can upload it to a persistent GPU
    # texture and alpha-blend it into the GPU HUD canvas.  Keeping the chart
    # bbox out of _bboxes removes the chart from the CPU dirty HUD upload too.
    gpu_capture_keys: Optional[set[str]] = None,
    gpu_capture: Optional[dict[str, dict[str, Any]]] = None,
    split_chart_keys: Optional[set[str]] = None,
    target_image: Optional[Image.Image] = None,
    coordinate_origin: tuple[int, int] = (0, 0),
    render_keys: Optional[set[str]] = None,
    destination_proven_empty: bool = False,
    map_heading: Optional[float] = None,
    async_map: bool = False,
) -> Image.Image:
    """Compose the complete HUD overlay image from all indicators.

    ``async_map`` (GUI preview only) makes map indicators render an immediate
    placeholder/overview and prepare detail tiles in the background instead of
    downloading synchronously on the GUI thread.  Final render / GPU paths
    leave it False (unchanged synchronous behaviour).
    """
    profiler = get_overlay_profiler()
    widget_fonts: dict[str, str] = {}

    def _font_for(key: str) -> str:
        if key not in widget_fonts:
            widget_fonts[key] = indicator_font_path(layout, key, font_path)
        return widget_fonts[key]
    origin_x, origin_y = coordinate_origin
    if target_image is not None:
        img = target_image
        prev_bboxes = None
        canvas_state = None
    elif reuse_canvas:
        c_type = "above" if (reuse_canvas == "above" or layout.get("_canvas_type") == "above") else "below"
        img, prev_bboxes, canvas_state = _get_reusable_canvas(canvas_w, canvas_h, canvas_type=c_type)
        if prev_bboxes:
            clear_started = time.perf_counter()
            pad = 40
            for bx, by, bw, bh in prev_bboxes.values():
                x1 = max(0, bx - pad)
                y1 = max(0, by - pad)
                x2 = min(canvas_w, bx + bw + pad)
                y2 = min(canvas_h, by + bh + pad)
                img.paste((0, 0, 0, 0), (x1, y1, x2, y2))
            prev_bboxes.clear()
            canvas_state["is_clean"] = True
            profiler.record(
                "canvas.regional_clear",
                (time.perf_counter() - clear_started) * 1000.0,
            )
        elif not canvas_state.get("is_clean", False):
            clear_started = time.perf_counter()
            img.paste((0, 0, 0, 0), (0, 0, canvas_w, canvas_h))
            canvas_state["is_clean"] = True
            profiler.record_full_canvas(
                "reusable_canvas_clear",
                (time.perf_counter() - clear_started) * 1000.0,
                "Initialize the persistent 3840x2160 RGBA HUD to transparent pixels",
            )
    else:
        img = Image.new("RGBA", (canvas_w, canvas_h), (0, 0, 0, 0))
        prev_bboxes = None
        canvas_state = None

    if _bboxes is None:
        _bboxes = {}

    def _paste_prior_bboxes() -> list[tuple[int, int, int, int]]:
        """Return prior geometry in the coordinate system of ``img``."""
        if target_image is None:
            return list(_bboxes.values())
        return [
            (bx - origin_x, by - origin_y, bw, bh)
            for bx, by, bw, bh in _bboxes.values()
        ]

    # Time display (multi-line info block) — the modern replacement for the
    # removed legacy ``time_block`` indicator.
    if "time_display" in layout.get("indicators", {}) and (
        render_keys is None or "time_display" in render_keys
    ):
        with indicator_scope("time_display"):
            with profiler.measure("indicator.time_display.render"):
                td, tdx, tdy = render_time_display(
                    canvas_w, canvas_h, layout, _font_for("time_display"),
                    date_text, time_text, elapsed_seconds, avg_speed_kmh,
                )
        if td:
            td_rotation = layout["indicators"]["time_display"].get("rotation", 0)
            cx = tdx + td.width // 2
            cy = tdy + td.height // 2
            with indicator_scope("time_display"):
                with profiler.measure("indicator.time_display.paste_composite"):
                    rotated_paste(
                        img, td, cx - origin_x, cy - origin_y, td_rotation,
                        prior_bboxes=_paste_prior_bboxes(), cache_key="time_display",
                        tight_bboxes=_tight_bboxes, tight_key="time_display",
                    )
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
            profiler.record_indicator_geometry(
                "time_display", _bboxes["time_display"], td.size,
                (canvas_w, canvas_h), 1, "time_display",
            )

    if indicator_values is None:
        indicator_values = {}

    # Map of all default built-in values
    known_vals: dict[str, tuple[float, str, str]] = {
        "speed_visual": (speed_value, "km/h", ""),
        "speed_text": (speed_value, "km/h", ""),
        "dist_visual": (None if distance_m is None else distance_m / 1000.0, "km", ""),
        "dist_text": (None if distance_m is None else distance_m / 1000.0, "km", ""),
        "alt_visual": (alt_value, "m", "Alt"),
        "alt_text": (alt_value, "m", "Alt"),
        "iso_text": (iso_value, "ISO", "ISO"),
        "exposure_text": (exposure_value, "", "Exp"),
        "temp_text": (temp_value, "\u00b0C", "Temp"),
        "power_text": (power_value, "W", "Moc"),
        "atemp_text": (atemp_value, "\u00b0C", "ATemp"),
        "hr_text": (hr_value, "BPM", "HR"),
        "cad_text": (cad_value, "RPM", "Cad"),
        "battery_text": (battery_value, "%", "Bat"),
        "slope_text": (None, "%", "Slope"),
        "lean_indicator": (None, "°", "Przechył"),
        "compass": (None, "°", "Compass"),
        "track_map": (0.0, "", "Mapa"),
    }

    # Overlay with extra indicators (e.g. FIT fields dynamically discovered).
    # NOTE (ETAP 11B): distance fields arriving via *extra_indicators* (e.g.
    # ``fit_distance_text``) carry RAW METERS (FIT/GPMF store distance in m).
    # They MUST be normalised to the display unit (km) exactly like the
    # built-in dist_visual/dist_text values, otherwise the renderer receives
    # ``10129.14`` with ``unit="km"`` -> "10129 km" text + marker pinned at 100%.
    def _dist_display_value(k: str, raw: Any) -> Any:
        if raw is None:
            return raw
        if "distance" in k or "dist_" in k:
            return raw / 1000.0
        return raw

    if extra_indicators:
        for k, v in extra_indicators.items():
            if isinstance(v, (tuple, list)) and len(v) >= 1:
                known_vals[k] = (_dist_display_value(k, v[0]), v[1], v[2] if len(v) >= 3 else k)
            else:
                known_vals[k] = _dist_display_value(k, v)

    # Apply per-indicator value overrides (built-in dist_visual/dist_text and
    # any custom distance key emitted through indicator_values).
    for k, raw in indicator_values.items():
        val = _dist_display_value(k, raw)
        if k in known_vals:
            _, u, l = known_vals[k]
            known_vals[k] = (val, u, l)
        else:
            known_vals[k] = (val, "", k)

    # Render ALL indicators configured in layout (GPMF, FIT, GPX, Custom)
    for key, ind_cfg in layout.get("indicators", {}).items():
        if key in _REMOVED_LEGACY_KEYS:
            # Legacy indicator (e.g. time_block) — removed from the program;
            # old projects keep loading but the indicator is never rendered.
            continue
        if key == "time_display":
            continue
        if render_keys is not None and key not in render_keys:
            continue
        if not ind_cfg or not ind_cfg.get("enabled", True):
            continue
        indicator_started = time.perf_counter()

        val_entry = known_vals.get(key)
        if val_entry is None or not isinstance(val_entry, (tuple, list)):
            value = val_entry
            default_unit = ind_cfg.get("unit", "")
            default_label = ind_cfg.get("label", key)
        else:
            value, default_unit, default_label = val_entry
        compass_missing = key == "compass" and value is None
        slope_missing = key == "slope_text" and value is None
        if compass_missing:
            value = 0.0
        if slope_missing:
            value = 0.0
        # An empty string in the layout must not suppress a sensible unit —
        # fall back to the default unit for the data source.
        unit = ind_cfg.get("unit") or default_unit
        label = ind_cfg.get("label", default_label)

        current_cfg = _effective_indicator_cfg(key, ind_cfg)
        if compass_missing:
            current_cfg["_compass_missing"] = True
        if slope_missing:
            current_cfg["_slope_missing"] = True

        # Dynamic max/min range scaling for visual bars/gauges.
        # Tylko JAWNY tryb AUTO (auto_scale=True) nadpisuje ręcznie ustawioną
        # skalę (min_val/max_val) pełnym zakresem telemetrii. Domyślnie
        # (auto_scale=False / brak pola) renderer SZANUJE ręczne min/max —
        # wcześniej ukryte AUTO nadpisywało max_val dystansu, np. 3 km -> 24 km.
        is_dist_key = key in ("dist_visual", "dist_text", "fit_distance_text") or (
            current_cfg.get("form") in ("bar", "gauge", "segment_bar")
            and (current_cfg.get("unit") == "km" or "distance" in key or "dist_" in key)
        )
        if (
            is_dist_key
            and current_cfg.get("auto_scale", False)
            and max_distance_m is not None
        ):
            current_cfg["max_val"] = max(current_cfg.get("min_val", 0) + 0.001, max_distance_m / 1000.0)
        elif (
            key in ("speed_visual", "speed_text")
            and current_cfg.get("auto_scale", False)
            and max_speed_kmh is not None
            and current_cfg.get("form") in ("bar", "gauge", "segment_bar")
        ):
            rounded = math.ceil(max_speed_kmh / 10.0) * 10
            current_cfg["max_val"] = max(current_cfg.get("min_val", 0) + 0.001, rounded)
        elif (
            key in ("alt_visual", "alt_text")
            and current_cfg.get("auto_scale", False)
            and min_alt is not None
            and max_alt is not None
        ):
            current_cfg["min_val"] = min_alt
            current_cfg["max_val"] = max(min_alt + 1.0, max_alt)

        # Formatting
        show_value = current_cfg.get("show_value", True)
        if not show_value:
            fv = ""
        else:
            default_decimals = 0 if key in ("iso_text", "exposure_text", "temp_text", "atemp_text", "power_text", "hr_text", "cad_text", "battery_text", "compass") or key.startswith("fit_") else 1
            decimals = int(current_cfg.get("decimals", default_decimals))
            show_units = current_cfg.get("show_units", True)

            if key == "compass":
                if compass_missing:
                    val_str = "--°"
                else:
                    rounded_heading = int(round(float(value))) % 360
                    heading_format = current_cfg.get("compass_heading_format", "03d")
                    if heading_format == "d":
                        val_str = f"{rounded_heading}°"
                    else:
                        val_str = f"{rounded_heading:03d}°"
            elif key == "slope_text":
                suffix = "%" if show_units else ""
                val_str = f"--{suffix}" if slope_missing else f"{float(value):+.{decimals}f}{suffix}"
            elif key == "exposure_text":
                val_str = f"1/{int(value)}" if value and int(value) > 0 else ""
            elif value is None:
                val_str = "--"
            else:
                val_str = f"{value:.{decimals}f}"

            if key in ("compass", "slope_text"):
                fv = val_str
            elif show_units:
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

        with indicator_scope(key):
            with profiler.measure(f"indicator.{key}.render"):
                res, rx, ry, extra = render_value_indicator(
                    canvas_w, canvas_h, layout, _font_for(key),
                    key, value, unit, label,
                    cfg_override=current_cfg,
                    formatted_val=fv,
                    max_distance_m=max_distance_m,
                    history_data=chart_vals,
                    current_position=current_position,
                    gps_track=gps_track,
                    supersample=ss,
                    target_dt=target_dt,
                    split_chart_keys=split_chart_keys,
                    map_heading=map_heading,
                    async_map=async_map,
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

            if rotation in (90, 270):
                bw, bh = res.height, res.width
            else:
                bw, bh = res.width, res.height
            widget_bbox = (
                int(center_x - bw // 2), int(center_y - bh // 2), int(bw), int(bh),
            )

            profiler.set_indicator_metadata(
                key,
                form=current_cfg.get("form", "text"),
                source=current_cfg.get("source", "gpmf"),
                rotation=rotation,
                supersample=int(ss),
            )
            profiler.record_indicator_geometry(
                key, widget_bbox, res.size, (canvas_w, canvas_h),
                int(ss), current_cfg.get("form", "text"),
            )

            # ETAP 5J: GPU chart compositing — render the chart on the CPU (raw
            # RGBA byte-identical) but hand it to the GPU blend instead of the
            # Pillow HUD.  The chart bbox deliberately stays out of _bboxes so
            # it also leaves the CPU dirty HUD upload.
            if (
                gpu_capture_keys
                and key in gpu_capture_keys
                and gpu_capture is not None
            ):
                # The GPU blend must place the chart at the EXACT top-left that
                # the CPU paste would use (rotated_paste: round(center - size/2),
                # which can differ by 1 px from the int(center - size//2) bbox).
                _rot = rotation % 360
                if _rot in (90, 270):
                    _disp_w, _disp_h = res.height, res.width
                else:
                    _disp_w, _disp_h = res.width, res.height
                paste_x = int(round(center_x - _disp_w / 2.0))
                paste_y = int(round(center_y - _disp_h / 2.0))
                if (split_chart_keys and key in split_chart_keys
                        and isinstance(res, ChartSplit)):
                    # ETAP 5K: hand back the static layer + the two small
                    # dynamic tiles (cursor / current value) with their local
                    # offsets inside the chart image.  The exporter uploads the
                    # static layer once and the dynamic tiles per frame.
                    gpu_capture[key] = {
                        "split": True,
                        "static": res.static,
                        "cursor_tile": res.cursor_tile,
                        "cursor_local": res.cursor_local,
                        "value_tile": res.value_tile,
                        "value_local": res.value_local,
                        "bbox": (paste_x, paste_y, _disp_w, _disp_h),
                        "center": (center_x, center_y),
                        "rotation": rotation,
                    }
                else:
                    gpu_capture[key] = {
                        "image": res,
                        "bbox": (paste_x, paste_y, _disp_w, _disp_h),
                        "center": (center_x, center_y),
                        "rotation": rotation,
                    }
            else:
                with indicator_scope(key):
                    with profiler.measure(f"indicator.{key}.paste_composite"):
                        rotated_paste(
                            img, res, center_x - origin_x, center_y - origin_y, rotation,
                            prior_bboxes=_paste_prior_bboxes(), cache_key=key,
                            destination_proven_empty=(
                                destination_proven_empty
                                and current_cfg.get("form", "text") == "chart"
                            ),
                            tight_bboxes=_tight_bboxes, tight_key=key,
                        )

                _bboxes[key] = widget_bbox

                # Extra text annotations / range labels
                annotation_started = time.perf_counter()
                with indicator_scope(key):
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
                            text_x = int(center_x + res.height // 2 + 8 + ox - origin_x)
                            text_y = int(center_y - text_h / 2 + oy - origin_y)
                        else:
                            text_x = int(center_x + extra["dot_x"] - res.width // 2 - text_w / 2 + ox - origin_x)
                            text_y = int(center_y + extra["dot_y"] - res.height // 2 - text_h - 8 + oy - origin_y)
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
                            draw.text((left_x - origin_x, left_y - origin_y), left_text, font=font, fill=(220, 220, 220, 255), stroke_width=outline, stroke_fill=(0, 0, 0, 255))
                            if right_text:
                                right_x = int(center_x - res.height // 2 + extra["x2"] + rox)
                                right_y = int(center_y - res.width // 2 - right_h / 2 + roy - rspreadx)
                                draw.text((right_x - origin_x, right_y - origin_y), right_text, font=font, fill=(220, 220, 220, 255), stroke_width=outline, stroke_fill=(0, 0, 0, 255))
                        else:
                            left_y = int(center_y - res.height // 2 + extra["by"] + 4 + roy)
                            left_x = int(center_x - res.width // 2 + extra["x1"] + rox)
                            draw.text((left_x - origin_x, left_y - origin_y), left_text, font=font, fill=(220, 220, 220, 255), stroke_width=outline, stroke_fill=(0, 0, 0, 255))
                            if right_text:
                                right_x = int(center_x - res.width // 2 + extra["x2"] - right_w + rox + rspreadx)
                                draw.text((right_x - origin_x, left_y - origin_y), right_text, font=font, fill=(220, 220, 220, 255), stroke_width=outline, stroke_fill=(0, 0, 0, 255))
                profiler.record(
                    f"indicator.{key}.annotations",
                    (time.perf_counter() - annotation_started) * 1000.0,
                )
        profiler.record(
            f"indicator.{key}.total",
            (time.perf_counter() - indicator_started) * 1000.0,
        )

    # Custom texts – use resolution-scaled outline
    ct_outline = max(0, int(round(
        int(layout.get("global", {}).get("text_outline", 3)) * min(canvas_w, canvas_h) / 1000
    )))
    for custom_index, ct_cfg in enumerate(layout.get("custom_texts", [])):
        if render_keys is not None and f"custom_text:{custom_index}" not in render_keys:
            continue
        ct_res, ctx, cty = render_custom_text(
            canvas_w, canvas_h, _font_for("custom_text"), ct_cfg, stroke_width=ct_outline
        )
        if ct_res:
            ct_rotation = int(ct_cfg.get("rotation", 0))
            rotated_paste(
                img, ct_res, ctx - origin_x, cty - origin_y, ct_rotation,
                prior_bboxes=_paste_prior_bboxes(), cache_key="custom_text",
                tight_bboxes=_tight_bboxes,
                tight_key=f"custom_text:{custom_index}",
            )
            # Keep the same conservative rendered geometry used by regular
            # indicators.  This lets CPU_ABOVE_MAP reuse actual custom-text
            # output without scanning the full canvas for alpha.
            if ct_rotation in (90, 270):
                ct_w, ct_h = ct_res.height, ct_res.width
            else:
                ct_w, ct_h = ct_res.width, ct_res.height
            _bboxes[f"custom_text:{custom_index}"] = (
                int(round(ctx - ct_w / 2)),
                int(round(cty - ct_h / 2)),
                int(ct_w),
                int(ct_h),
            )

    if prev_bboxes is not None and _bboxes:
        prev_bboxes.update(_bboxes)
        if canvas_state is not None:
            canvas_state["is_clean"] = False

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
    map_heading: Optional[float] = None,
    async_map: bool = False,
) -> Image.Image:
    """Render a preview image: source frame with HUD overlay composited on top.

    ``async_map=True`` (GUI preview) renders map widgets via the prepared
    MapContext overview/placeholder and never blocks the GUI thread.
    """
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
        map_heading=map_heading,
        async_map=async_map,
    )
    # Bypass OpenCL to check CPU alpha_composite performance
    img.alpha_composite(overlay)
    return img
