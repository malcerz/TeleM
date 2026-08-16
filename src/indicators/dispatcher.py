"""Dispatcher — routes indicator rendering to the correct per-form function.

Extracted from ``overlay_renderer.py``.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

try:
    from PIL import Image
except ImportError:
    Image = None  # type: ignore

from src.indicators.bar import _render_bar_indicator
from src.indicators.chart import _render_chart_indicator
from src.indicators.gauge import _render_gauge_indicator
from src.indicators.helpers import load_font, s
from src.indicators.moving_map import _render_moving_map_indicator
from src.indicators.segment_bar import _render_segment_bar_indicator
from src.indicators.static_map import _render_static_map_indicator
from src.indicators.text import _render_text_indicator


def render_value_indicator(
    canvas_w: int,
    canvas_h: int,
    layout: dict[str, Any],
    font_path: str,
    key: str,
    value: float,
    unit: str,
    label: str,
    cfg_override: Optional[dict[str, Any]] = None,
    formatted_val: Optional[str] = None,
    max_distance_m: Optional[float] = None,
    history_data: Optional[list[float] | dict[str, Any]] = None,
    current_position: Optional[float] = None,
    gps_track: Optional[list[tuple[Any, float, float]]] = None,
    supersample: int = 1,
    target_dt: Optional[datetime] = None,
    start_dt_utc: Optional[datetime] = None,
    split_chart_keys: Optional[set[str]] = None,
) -> tuple[Optional[Image.Image], int, int, Optional[dict[str, Any]]]:
    """Render a single telemetry indicator – dispatcher to per-form helpers."""
    cfg = cfg_override if cfg_override else layout["indicators"].get(key)
    if not cfg or not cfg.get("enabled", True):
        return None, 0, 0, None

    form = cfg.get("form", "text")
    _FORM_MAP = {"TEXT": "text", "SUWAK": "bar", "LICZNIK": "text"}
    form = _FORM_MAP.get(form, form)
    min_dim = min(canvas_w, canvas_h)
    outline_raw = int(layout["global"].get("text_outline", 3))
    outline = max(0, int(round(outline_raw * min_dim / 1000)))
    fs_val = cfg.get("font_size") if "font_size" in cfg else cfg.get("size", 0.02)
    fs = max(8, s(fs_val, min_dim))
    font = load_font(font_path, fs)

    val_min = float(cfg.get("min_val", 0))
    val_max = float(cfg.get("max_val", 100))
    ticks = int(cfg.get("ticks", 0))
    _thickness_raw = float(cfg.get("thickness", 1))
    if _thickness_raw >= 1:
        _thickness_rel = _thickness_raw / 200.0
    else:
        _thickness_rel = _thickness_raw
    thickness = max(1, s(_thickness_rel, min_dim))
    size_px = s(cfg.get("size", 0.1), min_dim if form == "gauge" else canvas_w)
    ss = max(1, supersample)

    _kwargs = dict(
        canvas_w=canvas_w, canvas_h=canvas_h,
        layout=layout, font_path=font_path,
        key=key, value=value, unit=unit, label=label,
        cfg=cfg, min_dim=min_dim, outline=outline,
        fs=fs, font=font,
        val_min=val_min, val_max=val_max,
        ticks=ticks, thickness=thickness, size_px=size_px, ss=ss,
    )

    if form == "text":
        return _render_text_indicator(**_kwargs, formatted_val=formatted_val)
    elif form == "bar":
        return _render_bar_indicator(**_kwargs, formatted_val=formatted_val)
    elif form == "gauge":
        return _render_gauge_indicator(**_kwargs, formatted_val=formatted_val)
    elif form == "chart":
        return _render_chart_indicator(
            **_kwargs,
            history_data=history_data,
            current_position=current_position,
            formatted_val=formatted_val,
            split_mode=bool(
                split_chart_keys is not None and key in split_chart_keys
            ),
        )
    elif form == "segment_bar":
        return _render_segment_bar_indicator(**_kwargs, formatted_val=formatted_val)
    elif form == "static_map":
        return _render_static_map_indicator(
            **_kwargs,
            gps_track=gps_track,
            target_dt=target_dt,
            current_position=current_position,
        )
    elif form == "map":
        return _render_moving_map_indicator(
            **_kwargs,
            gps_track=gps_track,
            target_dt=target_dt,
            current_position=current_position,
        )

    return None, 0, 0, None
