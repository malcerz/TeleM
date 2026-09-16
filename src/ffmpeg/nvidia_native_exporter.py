"""NVIDIA Native D3D11/NVENC Export Adapter for TeleM.

Executes single-pass live MP4 export with hardware D3D11VA decode,
Direct2D / DirectWrite HUD, native GPU map rotation, P010 VideoProcessor,
NVENC HEVC/AV1 encoding, PacedAudioFeeder (AAC stream copy), and live MP4 muxer.
"""

from __future__ import annotations

import os
import sys
import time
import math
import bisect
import hashlib
import json
import sqlite3
import ctypes
from ctypes import wintypes
import subprocess
import threading
import uuid
from collections import deque
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from src.ffmpeg.nvidia_config import (
    NvidiaBackend,
    LOCKED_PROFILES,
    resolve_nvidia_profile,
    get_native_dll_path,
    load_native_pipeline,
    TelemVideoClipDesc,
    TelemFrameState,
    TelemIndicatorDesc,
    TelemIndicatorStyle,
    TelemTextStyle,
    TelemTimeDisplayStyle,
    TelemBarStyle,
    TelemSegmentBarStyle,
    TelemGaugeStyle,
    TelemChartStyle,
    TelemMapStyle,
    TelemEncoderConfig,
    TelemNvencConfig,
    TelemProgressInfo,
    TelemPipelineStats,
    TelemCompressionStats,
)
from src.indicators.frame_data import compute_indicator_auto_ranges
from src.indicators.helpers import s
from src.process_lifecycle import RenderProcessRegistry


kernel32 = ctypes.windll.kernel32
CACHE_DIR = Path("scratch/audio_cache")
CACHE_DIR.mkdir(parents=True, exist_ok=True)


def parse_color_hex(hex_str: Optional[str], default: int = 0xFFFFFFFF) -> int:
    """Parse hex color string (#RRGGBB or #AARRGGBB) to 0xAARRGGBB uint32."""
    if not hex_str:
        return default
    s_val = hex_str.strip().lstrip("#")
    try:
        if len(s_val) == 6:
            return 0xFF000000 | int(s_val, 16)
        elif len(s_val) == 8:
            return int(s_val, 16)
    except Exception:
        pass
    return default


def _map_render_plan(canvas_w: int, canvas_box_px: int, target_zoom: int) -> dict:
    if canvas_box_px <= 0:
        canvas_box_px = 691
    desired_extent_m = (156543.03392 * math.cos(math.radians(52.0)) / (2.0 ** target_zoom)) * canvas_box_px
    best_zoom = target_zoom
    min_error = float("inf")
    best_offset = 0

    for candidate_zoom in range(12, 19):
        for candidate_offset in (0, 1, -1, 2, -2):
            actual_zoom = candidate_zoom + candidate_offset
            if actual_zoom != target_zoom:
                continue
            scale = 2.0 ** candidate_offset
            tile_extent = (156543.03392 * math.cos(math.radians(52.0)) / (2.0 ** candidate_zoom)) * (canvas_box_px / scale)
            err = abs(tile_extent - desired_extent_m)
            if err < min_error:
                min_error = err
                best_zoom = candidate_zoom
                best_offset = candidate_offset

    return {
        "effective_zoom": best_zoom,
        "zoom_offset": best_offset,
        "scale_factor": 2.0 ** best_offset,
    }


def _native_layout_key(desc: TelemIndicatorDesc) -> str:
    return bytes(desc.key).split(b"\0", 1)[0].decode("utf-8", errors="replace")


def _native_layout_px(cfg: dict[str, Any], canvas_w: int, canvas_h: int) -> tuple[float, float]:
    """Resolve the same top-left layout anchor used by the Legacy compositor."""
    return float(s(cfg.get("x", 0.0), canvas_w)), float(s(cfg.get("y", 0.0), canvas_h))


def _apply_native_layout_geometry(
    indicators: List[TelemIndicatorDesc],
    ind_cfg: dict[str, Any],
    canvas_w: int,
    canvas_h: int,
    min_dim: int,
) -> None:
    """Bind Native renderer anchors to the layout instead of old absolute pixels.

    The Native C++ widgets use style canvas fields when present.  The previous
    adapter populated those fields with coordinates from an older preset, so
    changing ``def_layout.json`` changed the descriptors but not the pixels.
    Keep the descriptor list/API intact and only translate each widget's local
    renderer anchor from the Legacy top-left layout anchor.
    """
    for desc in indicators:
        key = _native_layout_key(desc)
        cfg = ind_cfg.get(key)
        if not isinstance(cfg, dict):
            continue

        layout_x, layout_y = _native_layout_px(cfg, canvas_w, canvas_h)
        try:
            desc.rotation = float(int(float(cfg.get("rotation", 0) or 0)) % 360)
        except (TypeError, ValueError):
            desc.rotation = 0.0

        if int(desc.type) == 0:
            desc.style.text.canvas_x = layout_x + float(cfg.get("text_offset_x", 0.0) or 0.0) * canvas_w
            desc.style.text.canvas_y = layout_y + float(cfg.get("text_offset_y", 0.0) or 0.0) * canvas_h
        elif int(desc.type) == 1:
            desc.style.time_display.canvas_x = layout_x
            desc.style.time_display.canvas_y = layout_y
        elif int(desc.type) == 2:
            # Legacy horizontal rulers have a small local raster margin.  The
            # offsets below are local widget geometry; the layout-dependent
            # anchor is always ``layout_x/layout_y``.
            local_track_x = max(20.0, round(float(desc.width) * 0.0087))
            local_track_y = {
                "fit_distance_text": 167.0,
                "fit_solar_text": 172.0,
                "fit_curVpower_text": 111.0,
            }.get(key, 111.0)
            desc.style.bar.track_canvas_x = layout_x + local_track_x
            desc.style.bar.track_canvas_y = layout_y + local_track_y
            desc.style.bar.track_len = float(desc.width)
            # Derive title/range/value placement from the track, not from a
            # stale full-canvas coordinate.  The C++ renderer's fallback keeps
            # these elements in the same local relationship to the track.
            desc.style.bar.title_canvas_x = 0.0
            desc.style.bar.title_canvas_y = 0.0
            desc.style.bar.range_canvas_y = 0.0
            desc.style.bar.value_canvas_y = 0.0
        elif int(desc.type) == 3:
            # Vertical altitude ruler: track is at the right side of the
            # Legacy raster and spans its configured height.
            desc.style.bar.track_canvas_x = layout_x + float(desc.width) + 35.0
            desc.style.bar.track_canvas_y = layout_y + 8.0
            desc.style.bar.track_len = float(desc.height)
            desc.style.bar.value_canvas_y = 0.0
            desc.style.bar.range_canvas_y = 0.0
        elif int(desc.type) == 4:
            desc.style.segment_bar.seg_canvas_x = layout_x + 1.0
            desc.style.segment_bar.seg_canvas_y = layout_y + 15.0
            desc.style.segment_bar.seg_width = float(desc.width) + 2.0
            desc.style.segment_bar.value_canvas_x = 0.0
            desc.style.segment_bar.value_canvas_y = 0.0
            desc.style.segment_bar.label_canvas_x = 0.0
            desc.style.segment_bar.label_canvas_y = 0.0
        elif int(desc.type) == 5:
            # Legacy gauge returns a square raster whose side is 2.4 * the
            # configured radius.  GaugeIndicator expects its descriptor x/y
            # to be the center, not the Legacy raster's top-left corner.
            radius_px = float(s(cfg.get("size", 15.0), min_dim))
            side_px = float(int(radius_px * 2.4))
            desc.width = side_px
            desc.height = side_px
            desc.x = layout_x + side_px * 0.5
            desc.y = layout_y + side_px * 0.5
        elif int(desc.type) == 6:
            # Charts use the configured ``size`` in Legacy (not width/height
            # defaults).  ChartIndicator positions its descriptor by center.
            chart_w = float(s(cfg.get("size", 30.0), canvas_w)) + 8.0
            chart_h = max(40.0, chart_w * 0.4)
            chart_fs = float(max(14, s(cfg.get("font_size", 0.025), min_dim)))
            outline = float(max(0, int(round(3 * min_dim / 1000))))
            final_h = chart_h + (chart_fs + 8.0 + outline) + 4.0
            desc.width = chart_w
            desc.height = final_h
            desc.x = layout_x + chart_w * 0.5
            desc.y = layout_y + final_h * 0.5
            # Zero means ChartIndicator derives all plot/header/value anchors
            # from this descriptor's layout-relative geometry.
            desc.style.chart.plot_canvas_x1 = 0.0
            desc.style.chart.plot_canvas_y1 = 0.0
            desc.style.chart.plot_canvas_x2 = 0.0
            desc.style.chart.plot_canvas_y2 = 0.0
            desc.style.chart.header_canvas_x = 0.0
            desc.style.chart.header_canvas_y = 0.0
            desc.style.chart.value_canvas_x = 0.0
            desc.style.chart.value_canvas_y = 0.0


def build_canonical_indicators(layout: dict, auto_ranges: Optional[dict] = None) -> List[TelemIndicatorDesc]:
    canvas_w = 3840
    canvas_h = 2160
    min_dim = 2160
    indicators: List[TelemIndicatorDesc] = []
    ind_cfg = layout.get("indicators", {})

    # 1. time_display
    if "time_display" in ind_cfg:
        cfg_td = ind_cfg["time_display"]
        desc_td = TelemIndicatorDesc()
        desc_td.type = 1
        desc_td.key = b"time_display"
        desc_td.x = float(s(cfg_td.get("x", 0.35), canvas_w))
        desc_td.y = float(s(cfg_td.get("y", 4.73), canvas_h))
        desc_td.alpha = 1.0
        desc_td.z_order = 1
        master = 1.45
        global_fs = max(14, s(cfg_td.get("font_size", 0.025), min_dim))
        desc_td.style.time_display.font_family = "Arial"
        desc_td.style.time_display.global_font_size = float(global_fs)
        desc_td.style.time_display.outline_width = 6.0
        desc_td.style.time_display.show_date = 1 if cfg_td.get("show_date", True) else 0
        desc_td.style.time_display.show_time = 1 if cfg_td.get("show_time", True) else 0
        desc_td.style.time_display.show_elapsed = 1 if cfg_td.get("show_elapsed", True) else 0
        desc_td.style.time_display.show_avg_speed = 1 if cfg_td.get("show_avg_speed", True) else 0
        desc_td.style.time_display.date_label = str(cfg_td.get("date_label", "Data"))
        desc_td.style.time_display.time_label = str(cfg_td.get("time_label", "Godzina"))
        desc_td.style.time_display.elapsed_label = str(cfg_td.get("elapsed_label", "Czas"))
        desc_td.style.time_display.avg_speed_label = str(cfg_td.get("avg_speed_label", "Srednia predkosc"))
        desc_td.style.time_display.date_color = parse_color_hex(cfg_td.get("date_color"), 0xFFD2D2D2)
        desc_td.style.time_display.time_color = parse_color_hex(cfg_td.get("time_color"), 0xFFFFFFFF)
        desc_td.style.time_display.elapsed_color = parse_color_hex(cfg_td.get("elapsed_color"), 0xFFFFFFFF)
        desc_td.style.time_display.avg_speed_color = parse_color_hex(cfg_td.get("avg_speed_color"), 0xFFFFFFFF)
        desc_td.style.time_display.date_font_size = float(s(cfg_td.get("date_font_size", 1.5), min_dim) * master)
        desc_td.style.time_display.time_font_size = float(s(cfg_td.get("time_font_size", 1.5), min_dim) * master)
        desc_td.style.time_display.elapsed_font_size = float(s(cfg_td.get("elapsed_font_size", 1.5), min_dim) * master)
        desc_td.style.time_display.avg_speed_font_size = float(s(cfg_td.get("avg_speed_font_size", 1.1), min_dim) * master)
        desc_td.style.time_display.icon_name = b"clock"
        desc_td.style.time_display.icon_size = float(max(12, int(global_fs * master * 0.9)))
        desc_td.style.time_display.canvas_x = 13.0
        desc_td.style.time_display.canvas_y = 102.0
        desc_td.style.time_display.line_spacing = 58.0
        indicators.append(desc_td)

    # 2. exposure_text
    if "exposure_text" in ind_cfg:
        cfg = ind_cfg["exposure_text"]
        desc = TelemIndicatorDesc()
        desc.type = 0
        desc.key = b"exposure_text"
        desc.x = float(s(cfg.get("x", 0.66), canvas_w))
        desc.y = float(s(cfg.get("y", 90.75), canvas_h))
        desc.alpha = 1.0
        desc.z_order = 2
        desc.style.text.font_family = "Arial"
        desc.style.text.font_size = 54.0
        desc.style.text.text_color = parse_color_hex(cfg.get("text_color"), 0xFFFFFFFF)
        desc.style.text.outline_color = 0xFF000000
        desc.style.text.outline_width = 6.0
        desc.style.text.label = str(cfg.get("label", "Exp"))
        desc.style.text.icon_name = b"camera"
        desc.style.text.icon_size = 48.0
        desc.style.text.telemetry_field = 13
        desc.style.text.canvas_x = 25.0
        desc.style.text.canvas_y = 1960.0
        indicators.append(desc)

    # 3. iso_text
    if "iso_text" in ind_cfg:
        cfg = ind_cfg["iso_text"]
        desc = TelemIndicatorDesc()
        desc.type = 0
        desc.key = b"iso_text"
        desc.x = float(s(cfg.get("x", 0.66), canvas_w))
        desc.y = float(s(cfg.get("y", 85.0), canvas_h))
        desc.alpha = 1.0
        desc.z_order = 3
        desc.style.text.font_family = "Arial"
        desc.style.text.font_size = 54.0
        desc.style.text.text_color = parse_color_hex(cfg.get("text_color"), 0xFFFFFFFF)
        desc.style.text.outline_color = 0xFF000000
        desc.style.text.outline_width = 6.0
        desc.style.text.label = str(cfg.get("label", "ISO"))
        desc.style.text.icon_name = b"none"
        desc.style.text.telemetry_field = 12
        desc.style.text.canvas_x = 25.0
        desc.style.text.canvas_y = 1836.0
        indicators.append(desc)

    # 4. temp_text
    if "temp_text" in ind_cfg:
        cfg = ind_cfg["temp_text"]
        desc = TelemIndicatorDesc()
        desc.type = 0
        desc.key = b"temp_text"
        desc.x = float(s(cfg.get("x", 0.66), canvas_w))
        desc.y = float(s(cfg.get("y", 76.54), canvas_h))
        desc.alpha = 1.0
        desc.z_order = 4
        desc.style.text.font_family = "Arial"
        desc.style.text.font_size = 54.0
        desc.style.text.text_color = parse_color_hex(cfg.get("text_color"), 0xFFFFFFFF)
        desc.style.text.outline_color = 0xFF000000
        desc.style.text.outline_width = 6.0
        desc.style.text.label = str(cfg.get("label", "Temp"))
        desc.style.text.icon_name = b"temperature"
        desc.style.text.icon_size = 48.0
        desc.style.text.telemetry_field = 11
        desc.style.text.canvas_x = 25.0
        desc.style.text.canvas_y = 1653.0
        indicators.append(desc)

    # 5. fit_gopro_battery_text
    if "fit_gopro_battery_text" in ind_cfg:
        cfg = ind_cfg["fit_gopro_battery_text"]
        desc = TelemIndicatorDesc()
        desc.type = 0
        desc.key = b"fit_gopro_battery_text"
        desc.x = float(s(cfg.get("x", 0.66), canvas_w))
        desc.y = float(s(cfg.get("y", 69.79), canvas_h))
        desc.alpha = 1.0
        desc.z_order = 5
        desc.style.text.font_family = "Arial"
        desc.style.text.font_size = 54.0
        desc.style.text.text_color = parse_color_hex(cfg.get("text_color"), 0xFFFFFFFF)
        desc.style.text.outline_color = 0xFF000000
        desc.style.text.outline_width = 6.0
        desc.style.text.label = str(cfg.get("label", "Bat"))
        desc.style.text.icon_name = b"battery_full"
        desc.style.text.icon_size = 48.0
        desc.style.text.telemetry_field = 10
        desc.style.text.canvas_x = 25.0
        desc.style.text.canvas_y = 1507.0
        indicators.append(desc)

    # 6. fit_distance_text
    if "fit_distance_text" in ind_cfg:
        cfg = ind_cfg["fit_distance_text"]
        desc = TelemIndicatorDesc()
        desc.type = 2
        desc.key = b"fit_distance_text"
        desc.x = float(s(cfg.get("x", 50.0), canvas_w))
        desc.y = float(s(cfg.get("y", 96.3), canvas_h))
        desc.width = float(s(cfg.get("size", 60.0), canvas_w))
        desc.height = 80.0
        desc.alpha = 1.0
        desc.z_order = 6
        desc.style.bar.font_family = "Arial"
        desc.style.bar.title_font_size = 40.0
        desc.style.bar.range_font_size = 32.0
        desc.style.bar.value_font_size = 48.0
        desc.style.bar.outline_width = 6.0
        desc.style.bar.title = str(cfg.get("label", "Dystans"))
        desc.style.bar.unit = "km"
        desc.style.bar.show_label = 0
        desc.style.bar.show_range = 1
        desc.style.bar.show_value = 1
        desc.style.bar.show_mid = 1
        desc.style.bar.min_val = 0.0
        desc.style.bar.max_val = 7.80 if (auto_ranges and "fit_distance_text" in auto_ranges) else 10.0
        desc.style.bar.major_divisions = 10
        desc.style.bar.minor_per_major = 5
        desc.style.bar.major_len = 26.0
        desc.style.bar.minor_len = 16.0
        desc.style.bar.track_color = parse_color_hex(cfg.get("track_color"), 0xFFF4F4F4)
        desc.style.bar.tick_color = parse_color_hex(cfg.get("tick_color"), 0xFFF6F6F6)
        desc.style.bar.text_color = parse_color_hex(cfg.get("text_color"), 0xFFF4F4F4)
        desc.style.bar.marker_color = parse_color_hex(cfg.get("marker_color"), 0xFFFFFFFF)
        desc.style.bar.marker_size = 8.0
        desc.style.bar.marker_style = 0
        desc.style.bar.telemetry_field = 6
        desc.style.bar.track_canvas_x = 768.0
        desc.style.bar.track_canvas_y = 2073.0
        desc.style.bar.track_len = 2304.0
        desc.style.bar.title_canvas_x = 1724.0
        desc.style.bar.title_canvas_y = 54.0
        desc.style.bar.range_canvas_y = 2083.0
        desc.style.bar.value_canvas_y = 1978.0
        indicators.append(desc)

    # 7. fit_solar_text
    if "fit_solar_text" in ind_cfg:
        cfg = ind_cfg["fit_solar_text"]
        desc = TelemIndicatorDesc()
        desc.type = 2
        desc.key = b"fit_solar_text"
        desc.x = float(s(cfg.get("x", 90.95), canvas_w))
        desc.y = float(s(cfg.get("y", 17.48), canvas_h))
        desc.width = float(s(cfg.get("size", 15.0), canvas_w))
        desc.height = 80.0
        desc.alpha = 1.0
        desc.z_order = 7
        desc.style.bar.font_family = "Arial"
        desc.style.bar.title_font_size = 40.0
        desc.style.bar.range_font_size = 32.0
        desc.style.bar.value_font_size = 48.0
        desc.style.bar.outline_width = 6.0
        desc.style.bar.title = "SOLAR"
        desc.style.bar.unit = "%"
        desc.style.bar.show_label = 1
        desc.style.bar.show_range = 1
        desc.style.bar.show_value = 1
        desc.style.bar.show_mid = 1
        desc.style.bar.min_val = 0.0
        desc.style.bar.max_val = 30.0
        desc.style.bar.major_divisions = 5
        desc.style.bar.minor_per_major = 5
        desc.style.bar.major_len = 26.0
        desc.style.bar.minor_len = 16.0
        desc.style.bar.track_color = parse_color_hex(cfg.get("track_color"), 0xFFBCBCBC)
        desc.style.bar.tick_color = parse_color_hex(cfg.get("tick_color"), 0xFF828282)
        desc.style.bar.text_color = parse_color_hex(cfg.get("text_color"), 0xFFFFFFFF)
        desc.style.bar.marker_color = parse_color_hex(cfg.get("marker_color"), 0xFFFFE96E)
        desc.style.bar.marker_size = 8.0
        desc.style.bar.marker_style = 0
        desc.style.bar.telemetry_field = 8
        desc.style.bar.track_canvas_x = 3204.0
        desc.style.bar.track_canvas_y = 426.0
        desc.style.bar.track_len = 576.0
        label_ox = float(cfg.get("label_offset_x", -5.0))
        desc.style.bar.title_canvas_x = 3492.0 + label_ox
        desc.style.bar.title_canvas_y = 262.0
        desc.style.bar.range_canvas_y = 436.0
        desc.style.bar.value_canvas_y = 363.0
        desc.style.bar.value_offset_y = float(cfg.get("text_offset_y", 0.0))
        indicators.append(desc)

    # 8. alt_text
    if "alt_text" in ind_cfg:
        cfg = ind_cfg["alt_text"]
        desc = TelemIndicatorDesc()
        desc.type = 3
        desc.key = b"alt_text"
        desc.x = float(s(cfg.get("x", 95.95), canvas_w))
        desc.y = float(s(cfg.get("y", 51.47), canvas_h))
        desc.width = 120.0
        desc.height = float(s(cfg.get("size", 20.0), canvas_w))
        desc.alpha = 1.0
        desc.z_order = 8
        desc.style.bar.font_family = "Arial"
        desc.style.bar.title_font_size = 40.0
        desc.style.bar.range_font_size = 28.0
        desc.style.bar.value_font_size = 48.0
        desc.style.bar.outline_width = 6.0
        desc.style.bar.title = str(cfg.get("label", "Wys"))
        desc.style.bar.unit = "m"
        desc.style.bar.show_label = 0
        desc.style.bar.show_range = 1
        desc.style.bar.show_value = 1
        desc.style.bar.show_mid = 1
        desc.style.bar.show_tick_labels = 1
        if cfg.get("auto_scale", True) and auto_ranges and "alt_text" in auto_ranges:
            desc.style.bar.min_val = float(auto_ranges["alt_text"][0])
            desc.style.bar.max_val = float(auto_ranges["alt_text"][1])
        else:
            desc.style.bar.min_val = float(cfg.get("min_val", 0.0))
            desc.style.bar.max_val = float(cfg.get("max_val", 1000.0))
        desc.style.bar.major_divisions = int(cfg.get("major_ticks", 5))
        desc.style.bar.minor_per_major = int(cfg.get("minor_ticks", 10))
        desc.style.bar.major_len = 8.0
        desc.style.bar.minor_len = 8.0
        desc.style.bar.track_color = parse_color_hex(cfg.get("track_color"), 0xFFF4F4F4)
        desc.style.bar.tick_color = parse_color_hex(cfg.get("tick_color"), 0xFFF6F6F6)
        desc.style.bar.text_color = parse_color_hex(cfg.get("text_color"), 0xFFF4F4F4)
        desc.style.bar.marker_color = parse_color_hex(cfg.get("marker_color"), 0xFFFFFFFF)
        desc.style.bar.marker_size = 8.0
        desc.style.bar.marker_style = 0
        desc.style.bar.telemetry_field = 7
        desc.style.bar.track_canvas_x = 3624.0
        desc.style.bar.track_canvas_y = 725.0
        desc.style.bar.track_len = 768.0
        desc.style.bar.range_canvas_y = 725.0
        desc.style.bar.value_canvas_y = 3656.0
        indicators.append(desc)

    # 9. fit_curVpower_text
    if "fit_curVpower_text" in ind_cfg:
        cfg = ind_cfg["fit_curVpower_text"]
        desc = TelemIndicatorDesc()
        desc.type = 2
        desc.key = b"fit_curVpower_text"
        desc.x = float(s(cfg.get("x", 51.87), canvas_w))
        desc.y = float(s(cfg.get("y", 95.15), canvas_h))
        desc.width = float(s(cfg.get("size", 20.0), canvas_w))
        desc.height = 80.0
        desc.alpha = 1.0
        desc.z_order = 9
        desc.style.bar.font_family = "Arial"
        desc.style.bar.title_font_size = 40.0
        desc.style.bar.range_font_size = 32.0
        desc.style.bar.value_font_size = 48.0
        desc.style.bar.outline_width = 6.0
        desc.style.bar.title = ""
        desc.style.bar.unit = "W"
        desc.style.bar.show_label = 0
        desc.style.bar.show_range = 1
        desc.style.bar.show_value = 1
        desc.style.bar.show_mid = 1
        desc.style.bar.min_val = 0.0
        desc.style.bar.max_val = 359.0
        desc.style.bar.major_divisions = 10
        desc.style.bar.minor_per_major = 5
        desc.style.bar.major_len = 26.0
        desc.style.bar.minor_len = 16.0
        desc.style.bar.track_color = parse_color_hex(cfg.get("track_color"), 0xFFF4F4F4)
        desc.style.bar.tick_color = parse_color_hex(cfg.get("tick_color"), 0xFFF6F6F6)
        desc.style.bar.text_color = parse_color_hex(cfg.get("text_color"), 0xFFF4F4F4)
        desc.style.bar.marker_color = parse_color_hex(cfg.get("marker_color"), 0xFFFFFFFF)
        desc.style.bar.marker_size = 8.0
        desc.style.bar.marker_style = 0
        desc.style.bar.telemetry_field = 5
        desc.style.bar.track_canvas_x = 1608.0
        desc.style.bar.track_canvas_y = 2073.0
        desc.style.bar.track_len = 768.0
        desc.style.bar.title_canvas_x = 1608.0
        desc.style.bar.title_canvas_y = 1945.0
        desc.style.bar.range_canvas_y = 2083.0
        desc.style.bar.value_canvas_y = 1978.0
        indicators.append(desc)

    # 10. fit_garmin_battery_percent_text
    if "fit_garmin_battery_percent_text" in ind_cfg:
        cfg = ind_cfg["fit_garmin_battery_percent_text"]
        desc = TelemIndicatorDesc()
        desc.type = 4
        desc.key = b"fit_garmin_battery_percent_text"
        desc.x = float(s(cfg.get("x", 90.85), canvas_w))
        desc.y = float(s(cfg.get("y", 5.0), canvas_h))
        desc.width = float(s(cfg.get("size", 15.0), canvas_w))
        desc.height = 50.0
        desc.alpha = 1.0
        desc.z_order = 10
        desc.style.segment_bar.font_family = "Arial"
        desc.style.segment_bar.label_font_size = 36.0
        desc.style.segment_bar.value_font_size = 40.0
        desc.style.segment_bar.range_font_size = 30.0
        desc.style.segment_bar.outline_width = 6.0
        desc.style.segment_bar.label = str(cfg.get("label", "Garmin Battery %"))
        desc.style.segment_bar.unit = "%"
        desc.style.segment_bar.segments = 30
        desc.style.segment_bar.gap = 3.0
        desc.style.segment_bar.radius = 4.0
        desc.style.segment_bar.min_val = 0.0
        desc.style.segment_bar.max_val = 100.0
        desc.style.segment_bar.active_color = 0xFF32CD32
        desc.style.segment_bar.inactive_color = 0x3C333333
        desc.style.segment_bar.text_color = 0xFFFFFFFF
        desc.style.segment_bar.dim_color = 0xFFD0D0D0
        desc.style.segment_bar.grow_height = 1
        desc.style.segment_bar.grow_start = 0.40
        desc.style.segment_bar.telemetry_field = 9
        desc.style.segment_bar.active_color_start = 0xFF16A7AF
        desc.style.segment_bar.active_color_end = 0xFFFF9A2E
        desc.style.segment_bar.seg_canvas_x = 3199.0
        desc.style.segment_bar.seg_canvas_y = 70.0
        desc.style.segment_bar.seg_width = 578.0
        desc.style.segment_bar.seg_height = 68.0
        desc.style.segment_bar.value_canvas_x = 3199.0
        desc.style.segment_bar.value_canvas_y = 20.0
        desc.style.segment_bar.label_canvas_x = 3488.0
        desc.style.segment_bar.label_canvas_y = 145.0
        indicators.append(desc)

    # 11. speed_text (Speed Gauge)
    if "speed_text" in ind_cfg:
        cfg = ind_cfg["speed_text"]
        desc = TelemIndicatorDesc()
        desc.type = 5
        desc.key = b"speed_text"
        desc.x = float(s(cfg.get("x", 21.0), canvas_w))
        desc.y = float(s(cfg.get("y", 93.6), canvas_h))
        desc.width = float(s(cfg.get("size", 15.0), min_dim))
        desc.height = float(s(cfg.get("size", 15.0), min_dim))
        desc.alpha = 1.0
        desc.z_order = 11
        desc.style.gauge.font_family = "Arial"
        desc.style.gauge.gauge_font_size = 28.0
        desc.style.gauge.value_font_size = 90.0
        desc.style.gauge.unit_font_size = 28.0
        desc.style.gauge.outline_width = 6.0
        desc.style.gauge.unit = "km/h"
        desc.style.gauge.min_val = 0.0
        desc.style.gauge.max_val = 60.0
        desc.style.gauge.start_deg = 135.0
        desc.style.gauge.sweep_deg = 270.0
        desc.style.gauge.ticks = 0
        desc.style.gauge.step_val = 10.0
        desc.style.gauge.major_intervals = 6
        desc.style.gauge.sub_ticks_count = 5
        desc.style.gauge.needle_color = 0xFFDC3232
        desc.style.gauge.needle_length = 1.10
        desc.style.gauge.needle_width = 8.0
        desc.style.gauge.tick_color = 0xFFFFFFFF
        desc.style.gauge.text_color = 0xFFFFFFFF
        desc.style.gauge.telemetry_field = 2
        indicators.append(desc)

    # 12. fit_cadence_text (Cadence Chart)
    if "fit_cadence_text" in ind_cfg:
        cfg = ind_cfg["fit_cadence_text"]
        desc = TelemIndicatorDesc()
        desc.type = 6
        desc.key = b"fit_cadence_text"
        desc.x = float(s(cfg.get("x", 6.5), canvas_w))
        desc.y = float(s(cfg.get("y", 94.5), canvas_h))
        desc.width = float(s(cfg.get("width", 12.0), canvas_w))
        desc.height = float(s(cfg.get("height", 9.0), canvas_h))
        desc.alpha = 1.0
        desc.z_order = 12
        desc.style.chart.font_family = "Arial"
        desc.style.chart.header_font_size = 34.0
        desc.style.chart.axis_font_size = 26.0
        desc.style.chart.value_font_size = 46.0
        desc.style.chart.outline_width = 6.0
        desc.style.chart.label = str(cfg.get("label", "KADENCJA"))
        desc.style.chart.unit = "rpm"
        desc.style.chart.min_val = 0.0
        desc.style.chart.max_val = 86.0 if (auto_ranges and "fit_cadence_text" in auto_ranges) else 120.0
        desc.style.chart.line_color = parse_color_hex(cfg.get("chart_color"), 0xFF00AAFF)
        desc.style.chart.fill_color = parse_color_hex(cfg.get("fill_color"), 0xFF00AAFF)
        desc.style.chart.fill_alpha = float(cfg.get("fill_alpha", 80)) / 255.0
        desc.style.chart.grid_color = parse_color_hex(cfg.get("grid_color"), 0x66444444)
        desc.style.chart.text_color = parse_color_hex(cfg.get("text_color"), 0xFFF4F4F4)
        desc.style.chart.show_grid = 1
        desc.style.chart.show_x_axis = 0
        desc.style.chart.show_y_axis = 1
        desc.style.chart.label_count = 3
        desc.style.chart.telemetry_field = 4
        desc.style.chart.plot_canvas_x1 = 40.0
        desc.style.chart.plot_canvas_y1 = 1968.0
        desc.style.chart.plot_canvas_x2 = 472.0
        desc.style.chart.plot_canvas_y2 = 2124.0
        desc.style.chart.header_canvas_x = 40.0
        desc.style.chart.header_canvas_y = 1935.0
        desc.style.chart.value_canvas_x = 472.0
        desc.style.chart.value_canvas_y = 1935.0
        indicators.append(desc)

    # 13. fit_heart_rate_text (Heart Rate Chart)
    if "fit_heart_rate_text" in ind_cfg:
        cfg = ind_cfg["fit_heart_rate_text"]
        desc = TelemIndicatorDesc()
        desc.type = 6
        desc.key = b"fit_heart_rate_text"
        desc.x = float(s(cfg.get("x", 35.5), canvas_w))
        desc.y = float(s(cfg.get("y", 94.5), canvas_h))
        desc.width = float(s(cfg.get("width", 12.0), canvas_w))
        desc.height = float(s(cfg.get("height", 9.0), canvas_h))
        desc.alpha = 1.0
        desc.z_order = 13
        desc.style.chart.font_family = "Arial"
        desc.style.chart.header_font_size = 34.0
        desc.style.chart.axis_font_size = 26.0
        desc.style.chart.value_font_size = 46.0
        desc.style.chart.outline_width = 6.0
        desc.style.chart.label = str(cfg.get("label", "TĘTNO"))
        desc.style.chart.unit = "bpm"
        desc.style.chart.min_val = 78.0 if (auto_ranges and "fit_heart_rate_text" in auto_ranges) else 60.0
        desc.style.chart.max_val = 109.0 if (auto_ranges and "fit_heart_rate_text" in auto_ranges) else 180.0
        desc.style.chart.line_color = parse_color_hex(cfg.get("chart_color"), 0xFFFF3232)
        desc.style.chart.fill_color = parse_color_hex(cfg.get("fill_color"), 0xFFFF3232)
        desc.style.chart.fill_alpha = float(cfg.get("fill_alpha", 80)) / 255.0
        desc.style.chart.grid_color = parse_color_hex(cfg.get("grid_color"), 0x66444444)
        desc.style.chart.text_color = parse_color_hex(cfg.get("text_color"), 0xFFF4F4F4)
        desc.style.chart.show_grid = 1
        desc.style.chart.show_x_axis = 0
        desc.style.chart.show_y_axis = 1
        desc.style.chart.label_count = 3
        desc.style.chart.telemetry_field = 3
        desc.style.chart.plot_canvas_x1 = 1152.0
        desc.style.chart.plot_canvas_y1 = 1968.0
        desc.style.chart.plot_canvas_x2 = 1584.0
        desc.style.chart.plot_canvas_y2 = 2124.0
        desc.style.chart.header_canvas_x = 1152.0
        desc.style.chart.header_canvas_y = 1935.0
        desc.style.chart.value_canvas_x = 1584.0
        desc.style.chart.value_canvas_y = 1935.0
        indicators.append(desc)

    _apply_native_layout_geometry(indicators, ind_cfg, canvas_w, canvas_h, min_dim)
    return indicators


def build_map_indicator_desc(layout: dict, canvas_w: int = 3840, canvas_h: int = 2160) -> Optional[TelemIndicatorDesc]:
    ind_cfg = layout.get("indicators", {})
    if "track_map" not in ind_cfg:
        return None

    cfg = ind_cfg["track_map"]
    desc = TelemIndicatorDesc()
    desc.type = 7  # TELEM_IND_MAP
    desc.key = b"track_map"

    rx = float(s(cfg.get("x", 10.31), canvas_w))
    ry = float(s(cfg.get("y", 35.8), canvas_h))
    raw_size = float(s(cfg.get("size", 18.0), canvas_w))

    configured_zoom = int(cfg.get("zoom", 15))
    render_plan = _map_render_plan(canvas_w, int(round(raw_size)), configured_zoom)
    effective_zoom = render_plan["effective_zoom"]

    desc.x = rx
    desc.y = ry
    desc.width = float(int(round(raw_size)))
    desc.height = float(int(round(raw_size)))
    desc.alpha = 1.0
    desc.z_order = 14

    desc.style.map.canvas_x = rx
    desc.style.map.canvas_y = ry
    desc.style.map.width = float(int(round(raw_size)))
    desc.style.map.height = float(int(round(raw_size)))
    desc.style.map.zoom = effective_zoom
    desc.style.map.rotate_map = 1 if cfg.get("map_orientation", "track_up") == "track_up" else 0
    desc.style.map.alpha = 1.0
    desc.style.map.track_width = float(cfg.get("track_width", 5.0))
    desc.style.map.track_color = parse_color_hex(cfg.get("track_color"), 0xFFFF3C1E)
    desc.style.map.marker_radius = float(cfg.get("marker_size", 10.0))
    desc.style.map.marker_color = parse_color_hex(cfg.get("marker_color"), 0xFFFFFFFF)
    desc.style.map.marker_border_color = parse_color_hex(cfg.get("marker_border_color"), 0xFF000000)
    desc.style.map.border_color = parse_color_hex(cfg.get("border_color"), 0xFFFFFFFF)
    desc.style.map.border_width = float(cfg.get("border_width", 4.0))
    desc.style.map.corner_radius = float(cfg.get("corner_radius", 16.0))
    desc.style.map.marker_style = 1 if cfg.get("marker_style", "directional") == "directional" else 0
    try:
        desc.rotation = float(int(float(cfg.get("rotation", 0) or 0)) % 360)
    except (TypeError, ValueError):
        desc.rotation = 0.0

    return desc


def preload_sqlite_tiles_to_native(dll: ctypes.CDLL, handle: Any, zoom: int, style: str = "satellite") -> int:
    """Preload map tiles from local sqlite cache into native D3D11 tile textures."""
    db_path = Path.home() / ".telem_map_tiles" / "tilecache.sqlite"
    if not db_path.exists():
        return 0

    try:
        conn = sqlite3.connect(str(db_path))
        cur = conn.cursor()
        cur.execute("SELECT z, x, y, data FROM tiles WHERE z=? AND style=?", (zoom, style))
        rows = cur.fetchall()
        count = 0
        for z, x, y, data in rows:
            c_data = (ctypes.c_char * len(data)).from_buffer_copy(data)
            if dll.telem_nvenc_preload_map_tile(handle, z, x, y, c_data, len(data)):
                count += 1
        conn.close()
        return count
    except Exception:
        return 0


def get_cached_clip_adts(clip_path: str) -> bytes:
    """Extract AAC audio bitstream to ADTS format, cached on disk."""
    src = Path(clip_path).resolve()
    cache_file = CACHE_DIR / f"{src.stem}_audio.adts"
    if cache_file.exists() and cache_file.stat().st_size > 0:
        return cache_file.read_bytes()

    cmd = ["ffmpeg", "-v", "error", "-i", str(src), "-map", "0:a", "-c:a", "copy", "-f", "adts", "-"]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    out_data, err_data = proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError(f"Failed to demux audio from {src}: {err_data.decode(errors='ignore')}")
    cache_file.write_bytes(out_data)
    return out_data


def parse_adts_packets(data: bytes) -> List[bytes]:
    idx = 0
    packets = []
    n = len(data)
    while idx + 7 <= n:
        if data[idx] == 0xFF and (data[idx+1] & 0xF0) == 0xF0:
            frame_len = ((data[idx+3] & 0x03) << 11) | (data[idx+4] << 3) | ((data[idx+5] & 0xE0) >> 5)
            if frame_len <= 7 or idx + frame_len > n:
                break
            packets.append(data[idx:idx+frame_len])
            idx += frame_len
        else:
            idx += 1
    return packets


class PacedAudioFeeder:
    """Dual-channel live audio pipe feeder for smooth audio/video muxing."""
    def __init__(self, pipe_name: str, packets: List[bytes], lead_s: float = 1.0):
        self.pipe_name = pipe_name
        self.packets = packets
        self.total_pkts = len(packets)
        self.lead_s = lead_s
        self.cur_pkt_idx = 0
        self.video_time_s = 0.0
        self.stop_requested = False
        self.finished = False
        self.error: Optional[str] = None
        self.bytes_sent = 0
        self.pkts_sent = 0
        self.h_pipe = None
        self.thread: Optional[threading.Thread] = None

    def update_video_time(self, v_time_s: float) -> None:
        self.video_time_s = v_time_s

    def stop(self) -> None:
        self.stop_requested = True

    def start(self) -> None:
        self.h_pipe = kernel32.CreateNamedPipeW(
            self.pipe_name,
            0x00000003,  # PIPE_ACCESS_DUPLEX
            0x00000000,  # byte mode
            1,           # 1 instance
            1024 * 1024, # 1 MB buffer
            1024 * 1024, # 1 MB buffer
            0, None
        )
        if self.h_pipe in (-1, 0, None):
            raise RuntimeError(f"CreateNamedPipeW failed: {kernel32.GetLastError()}")
        self.thread = threading.Thread(target=self._worker, daemon=True, name="PacedAudioFeeder")
        self.thread.start()

    def _worker(self) -> None:
        try:
            kernel32.ConnectNamedPipe(self.h_pipe, None)
            bytes_w = wintypes.DWORD()

            while not self.stop_requested and self.cur_pkt_idx < self.total_pkts:
                audio_time_s = self.pkts_sent * (1024.0 / 48000.0)
                lead = audio_time_s - self.video_time_s

                if lead > self.lead_s:
                    time.sleep(0.01)
                    continue

                batch = bytearray()
                batch_pkts = 0
                while self.cur_pkt_idx < self.total_pkts and batch_pkts < 10:
                    batch.extend(self.packets[self.cur_pkt_idx])
                    self.cur_pkt_idx += 1
                    batch_pkts += 1

                if batch:
                    buf = (ctypes.c_char * len(batch)).from_buffer(batch)
                    res = kernel32.WriteFile(self.h_pipe, buf, len(batch), ctypes.byref(bytes_w), None)
                    if not res:
                        break
                    self.bytes_sent += bytes_w.value
                    self.pkts_sent += batch_pkts

            kernel32.FlushFileBuffers(self.h_pipe)
            kernel32.DisconnectNamedPipe(self.h_pipe)
        except Exception as ex:
            self.error = str(ex)
        finally:
            if self.h_pipe:
                kernel32.CloseHandle(self.h_pipe)
                self.h_pipe = None
            self.finished = True

    def join(self, timeout: float = 5.0) -> None:
        if self.thread:
            self.thread.join(timeout)


def build_streaming_audio_slice(
    clips_desc: List[TelemVideoClipDesc],
    start_frame: int,
    frame_count: int,
    fps_num: int = 30000,
    fps_den: int = 1001,
    progress_cb: Optional[Callable[[int, int, str], None]] = None,
) -> List[bytes]:
    fps = fps_num / float(fps_den)
    selected_packets: List[bytes] = []
    total_clips = len(clips_desc)

    for c_idx, clip in enumerate(clips_desc):
        if progress_cb:
            progress_cb(c_idx, total_clips, f"Klip {c_idx+1}/{total_clips}")
        clip_global_start_f = clip.global_start_frame
        clip_global_end_f = clip.global_start_frame + clip.frame_count

        overlap_start_f = max(start_frame, clip_global_start_f)
        overlap_end_f = min(start_frame + frame_count, clip_global_end_f)

        if overlap_start_f < overlap_end_f:
            local_start_s = (overlap_start_f - clip_global_start_f) / fps
            local_end_s = (overlap_end_f - clip_global_start_f) / fps
            local_dur_s = local_end_s - local_start_s

            adts_data = get_cached_clip_adts(clip.path)
            clip_pkts = parse_adts_packets(adts_data)

            start_pkt_idx = int(round(local_start_s * 48000.0 / 1024.0))
            pkt_count = int(round(local_dur_s * 48000.0 / 1024.0))

            clip_slice = clip_pkts[start_pkt_idx : start_pkt_idx + pkt_count]
            selected_packets.extend(clip_slice)

        if progress_cb:
            progress_cb(c_idx + 1, total_clips, f"Klip {c_idx+1}/{total_clips}")

    return selected_packets


def export_nvidia_native_d3d11(
    *,
    input_files: List[Any],
    output_file: Path | str,
    layout: dict,
    telemetry: Any,
    video_timeline: Optional[Any] = None,
    codec: str = "HEVC",
    quality_profile: str = "Quality",
    video_bitrate: str | float = "40M",
    enable_compression_analysis: bool = True,
    compression_csv_path: Optional[Path | str] = None,
    progress_cb: Optional[Callable[[int, str], None]] = None,
    on_render_progress: Optional[Callable[[int, int, float, float, dict], None]] = None,
    cancel_event: Optional[threading.Event] = None,
    active_process_holder: Optional[dict] = None,
    max_frames: Optional[int] = None,
    start_frame: int = 0,
    enable_preview: bool = False,
    preview_width: int = 960,
    preview_height: int = 540,
    preview_fps: float = 8.0,
    on_preview_frame: Optional[Callable[[bytes, int, int, int, int, float], None]] = None,
    gui_runtime_snapshot: Optional[dict[str, Any]] = None,
) -> bool:
    """Execute complete single-pass NVIDIA Native D3D11/NVENC export."""
    override = os.environ.get("TELEM_NVENC_DLL_OVERRIDE")
    active_dll_path = get_native_dll_path()
    active_dll_bytes = active_dll_path.read_bytes() if active_dll_path.exists() else b""
    active_dll_sha = hashlib.sha256(active_dll_bytes).hexdigest()

    if override:
        print("[NVIDIA DLL] override active", flush=True)
        print(f"[NVIDIA DLL] path={active_dll_path}", flush=True)
        print(f"[NVIDIA DLL] sha256={active_dll_sha}", flush=True)
        EXPECTED_GOOD_SHA = "d1a7ebee929aa08e445fc198c0aaf96aa2859ee4c128215566733b37d472bcea"
        if active_dll_sha.lower() != EXPECTED_GOOD_SHA.lower():
            print(f"[NVIDIA DLL] FATAL: SHA256 mismatch! Got {active_dll_sha}, expected {EXPECTED_GOOD_SHA}. ABORTING RENDER.", flush=True)
            raise RuntimeError(f"NVIDIA DLL override SHA256 mismatch: {active_dll_sha}")

    if os.environ.get("TELEM_DUMP_PAYLOAD", "0") == "1":
        try:
            from src.ffmpeg.nvidia_payload_dump import dump_canonical_payload
            dump_data = dump_canonical_payload(
                input_files=input_files,
                output_file=output_file,
                layout=layout,
                telemetry=telemetry,
                video_timeline=video_timeline,
                codec=codec,
                quality_profile=quality_profile,
                video_bitrate=video_bitrate,
                enable_compression_analysis=enable_compression_analysis,
                compression_csv_path=compression_csv_path,
                max_frames=max_frames,
                start_frame=start_frame,
                enable_preview=enable_preview,
                preview_width=preview_width,
                preview_height=preview_height,
                preview_fps=preview_fps,
                gui_runtime_snapshot=gui_runtime_snapshot,
            )
            dump_target = os.environ.get(
                "TELEM_PAYLOAD_DUMP_PATH",
                "scratch/nvidia_payload_diff/runtime_export_payload.json",
            )
            p_dt = Path(dump_target)
            p_dt.parent.mkdir(parents=True, exist_ok=True)
            p_dt.write_text(json.dumps(dump_data, indent=2), encoding="utf-8")
        except Exception as _dump_exc:
            print(f"[PAYLOAD DUMP WARNING] {_dump_exc!r}", flush=True)

    # 1. Resolve Profile and Bitrate
    profile_name = resolve_nvidia_profile(codec, quality_profile)
    spec = LOCKED_PROFILES[profile_name]

    # Bitrate parsing
    bitrate_mbps = 40.0
    if isinstance(video_bitrate, (int, float)):
        bitrate_mbps = float(video_bitrate)
    elif isinstance(video_bitrate, str):
        b_str = video_bitrate.strip().upper()
        if b_str.endswith("M"):
            bitrate_mbps = float(b_str[:-1])
        elif b_str.endswith("K"):
            bitrate_mbps = float(b_str[:-1]) / 1000.0
        elif "MBPS" in b_str:
            bitrate_mbps = float(b_str.replace("MBPS", "").strip())
        else:
            try:
                bitrate_mbps = float(b_str)
                if bitrate_mbps > 10000:
                    bitrate_mbps /= 1_000_000.0
            except ValueError:
                bitrate_mbps = 40.0

    output_final_path = Path(output_file).resolve()
    output_tmp_path = output_final_path.with_name(output_final_path.stem + ".tmp.mp4")

    if output_final_path.exists():
        output_final_path.unlink()
    if output_tmp_path.exists():
        output_tmp_path.unlink()

    # 2. Build Video Sequence Descriptors
    clips_desc: List[TelemVideoClipDesc] = []
    fps_num = 30000
    fps_den = 1001
    fps = fps_num / float(fps_den)

    global_frame_cursor = 0
    global_time_cursor = 0.0

    from src.video_helpers import ffprobe_stream_info, find_executable
    ffprobe_exe = find_executable("ffprobe") or "ffprobe"

    for file_item in input_files:
        p = Path(getattr(file_item, "path", file_item)).resolve()
        nb_frames = getattr(file_item, "frame_count", 0) or 0
        dur_s = float(getattr(file_item, "duration_sec", 0.0) or getattr(file_item, "duration", 0.0) or 0.0)

        if nb_frames <= 0 or dur_s <= 0:
            info = ffprobe_stream_info(ffprobe_exe, p)
            streams = info.get("streams", [])
            v_stream = streams[0] if streams else {}
            if nb_frames <= 0:
                nb_frames = int(v_stream.get("nb_frames", 0) or 0)
            if dur_s <= 0:
                dur_s = float(v_stream.get("duration", 0.0) or info.get("format", {}).get("duration", 0.0) or 0.0)
            if nb_frames <= 0 and dur_s > 0:
                nb_frames = int(round(dur_s * fps))

        clip_desc = TelemVideoClipDesc(
            path=str(p),
            frame_count=nb_frames,
            duration_sec=dur_s if dur_s > 0 else (nb_frames * fps_den / float(fps_num)),
            fps_num=fps_num,
            fps_den=fps_den,
            global_start_frame=global_frame_cursor,
            global_start_time=global_time_cursor,
        )
        clips_desc.append(clip_desc)
        global_frame_cursor += nb_frames
        global_time_cursor += clip_desc.duration_sec

    total_timeline_frames = global_frame_cursor
    export_frames = total_timeline_frames if max_frames is None else min(max_frames, total_timeline_frames)

    # 3. Setup Telemetry States & Indicators
    from src.render_progress import HudPrepProgressTracker

    prep_tracker = HudPrepProgressTracker(
        phases=[
            ("indicators", "Wskaźniki i layout", 0.01),
            ("telemetry_states", "Telemetria klatek", 0.94),
            ("audio_slice", "Przygotowanie audio", 0.03),
            ("native_setup", "Zasoby GPU i mapa", 0.02),
        ],
        callback=on_render_progress,
        backend_name="NVIDIA_NATIVE_D3D11",
    )

    prep_tracker.start_phase("indicators", items_total=len(layout.get("indicators", {})) or 1)
    auto_ranges = compute_indicator_auto_ranges(
        layout,
        speed_samples=getattr(telemetry, "speed_samples", None),
        alt_samples=getattr(telemetry, "alt_samples", None),
        iso_samples=getattr(telemetry, "iso_samples", None),
        exposure_samples=getattr(telemetry, "exposure_samples", None),
        temperature_samples=getattr(telemetry, "temperature_samples", None),
        fit_data=getattr(telemetry, "fit_data", {}),
    )

    indicators_list = build_canonical_indicators(layout, auto_ranges)
    map_desc = build_map_indicator_desc(layout)
    if map_desc:
        indicators_list.append(map_desc)
    prep_tracker.complete_phase("indicators")

    # Precompute global telemetry states (fast rate-aware & vectorized)
    from src.telemetry_states_fast import compute_fast_telemetry_states

    prep_tracker.start_phase("telemetry_states", items_total=export_frames)
    states = compute_fast_telemetry_states(
        telemetry=telemetry,
        video_timeline=video_timeline,
        export_frames=export_frames,
        fps=fps,
        prep_tracker=prep_tracker,
        chunk_size=500,
    )
    prep_tracker.complete_phase("telemetry_states")

    chart_samples_dict = {
        "cadence": [st.cadence_rpm for st in states[::30]],
        "heart_rate": [st.heart_rate_bpm for st in states[::30]],
    }
    route_points = [(p[0], p[1], p[2]) for p in track] if track else []

    if os.environ.get("TELEM_PAYLOAD_BISECT_MODE") in ("exact_good330", "clean_child_exact_good330"):
        actual_state_count = len(states)
        actual_cadence_count = len(chart_samples_dict["cadence"])
        actual_hr_count = len(chart_samples_dict["heart_rate"])
        actual_export_frames = export_frames

        print(f"[EXACT GOOD330 CHECK] requested frame count = {max_frames}", flush=True)
        print(f"[EXACT GOOD330 CHECK] actual telemetry state count = {actual_state_count}", flush=True)
        print(f"[EXACT GOOD330 CHECK] actual chart sample count = {actual_cadence_count}", flush=True)
        print(f"[EXACT GOOD330 CHECK] actual native start_export frame count = {actual_export_frames}", flush=True)

        if (
            max_frames != 330
            or actual_state_count != 330
            or actual_cadence_count != 11
            or actual_hr_count != 11
            or actual_export_frames != 330
        ):
            print("[EXACT GOOD330 CHECK] FATAL: EXACT GOOD330 PAYLOAD NOT ACHIEVED! STOPPING RENDER.", flush=True)
            raise RuntimeError("EXACT GOOD330 PAYLOAD NOT ACHIEVED")
        else:
            print("[EXACT GOOD330 CHECK] VERIFIED: All counts match EXACT GOOD330 specification!", flush=True)

    # 4. Audio Feeder Setup
    prep_tracker.start_phase("audio_slice", items_total=len(clips_desc) or 1)
    audio_packets = build_streaming_audio_slice(
        clips_desc, start_frame, export_frames, fps_num, fps_den,
        progress_cb=lambda done, tot, det: prep_tracker.update(done, tot, detail=det),
    )
    has_audio = len(audio_packets) > 0
    audio_feeder = None
    pipe_audio_name = None

    if has_audio:
        pipe_token = uuid.uuid4().hex[:8]
        pipe_audio_name = rf"\\.\pipe\telem_audio_{os.getpid()}_{pipe_token}"
        audio_feeder = PacedAudioFeeder(pipe_audio_name, audio_packets, lead_s=1.0)
        audio_feeder.start()
    prep_tracker.complete_phase("audio_slice")

    # 5. Video Pipe & Live FFmpeg MP4 Muxer
    prep_tracker.start_phase("native_setup", items_total=1)
    import msvcrt
    MAX_VIDEO_BACKLOG_BYTES = 16 * 1024 * 1024
    h_read_v = wintypes.HANDLE()
    h_write_v = wintypes.HANDLE()
    res_p = kernel32.CreatePipe(ctypes.byref(h_read_v), ctypes.byref(h_write_v), None, MAX_VIDEO_BACKLOG_BYTES)
    if not res_p:
        if audio_feeder:
            audio_feeder.stop()
        raise RuntimeError(f"CreatePipe failed with error {kernel32.GetLastError()}")

    kernel32.SetHandleInformation(h_read_v, 0x00000001, 1)
    kernel32.SetHandleInformation(h_write_v, 0x00000001, 0)
    fd_read_v = msvcrt.open_osfhandle(h_read_v.value, os.O_RDONLY)

    v_fmt = spec["ffmpeg_fmt"]
    v_tag = spec["vtag"]

    cmd_mux = [
        "ffmpeg", "-y",
        "-f", v_fmt, "-r", "30000/1001", "-i", "-",
    ]
    if has_audio and pipe_audio_name:
        cmd_mux.extend(["-f", "aac", "-i", pipe_audio_name, "-map", "0:v", "-map", "1:a", "-c:a", "copy"])
    else:
        cmd_mux.extend(["-map", "0:v"])

    cmd_mux.extend([
        "-c:v", "copy",
        "-tag:v", v_tag,
        "-f", "mp4",
        "-progress", "pipe:1",
        str(output_tmp_path),
    ])

    proc_mux = subprocess.Popen(
        cmd_mux,
        stdin=fd_read_v,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    os.close(fd_read_v)
    c_output_arg = f"HANDLE:{int(h_write_v.value)}"

    mux_stderr_lines = deque(maxlen=100)

    def progress_worker():
        try:
            for _ in proc_mux.stdout:
                pass
        except Exception:
            pass

    def stderr_worker():
        try:
            for line in proc_mux.stderr:
                l_str = line.decode(errors="ignore").strip()
                if l_str:
                    mux_stderr_lines.append(l_str)
        except Exception:
            pass

    t_prog = threading.Thread(target=progress_worker, daemon=True)
    t_prog.start()
    t_err = threading.Thread(target=stderr_worker, daemon=True)
    t_err.start()

    if active_process_holder is not None:
        active_process_holder["process"] = proc_mux
    try:
        RenderProcessRegistry.get_instance().register_child(proc_mux.pid)
    except Exception:
        pass


    # 6. Load Native Pipeline & Configure
    dll = load_native_pipeline()
    handle = dll.telem_nvenc_create()
    if not handle:
        proc_mux.kill()
        if audio_feeder:
            audio_feeder.stop()
        raise RuntimeError("telem_nvenc_create failed")

    target_bps = int(bitrate_mbps * 1_000_000)
    max_bps = int(target_bps * 1.25)
    vbv_bits = target_bps

    csv_path_str = str(Path(compression_csv_path).resolve()) if compression_csv_path else ""
    enc_cfg = TelemEncoderConfig(
        codec=spec["codec"],
        quality_mode=spec["quality_mode"],
        bit_depth=10,
        bitrate_bps=target_bps,
        max_bitrate_bps=max_bps,
        vbv_size_bits=vbv_bits,
        gop_length=250,
        b_frames=0,
        multipass=0,
        enable_lookahead=0,
        lookahead_depth=0,
        enable_aq=0,
        aq_strength=0,
        enable_temporal_aq=0,
        enable_compression_analysis=1 if enable_compression_analysis else 0,
        compression_csv_path=csv_path_str,
    )

    cfg = TelemNvencConfig(
        width=3840,
        height=2160,
        fps_num=fps_num,
        fps_den=fps_den,
        ring_size=0,
        bit_depth=10,
        preset_p1_to_p7=1,
        tuning_info=1,
        async_nvenc=1,
        enable_debug_layer=0,
        encoder_config=enc_cfg,
    )

    # Production-GUI provenance snapshot.  This is intentionally opt-in at
    # the GUI dispatch boundary, so direct Python/harness calls cannot produce
    # evidence that looks like a real Render-button export.
    if gui_runtime_snapshot and gui_runtime_snapshot.get("origin") == "TeleM GUI Render button":
        def _sha256(path_value: Any) -> Optional[str]:
            if not path_value:
                return None
            path = Path(path_value).resolve()
            if not path.is_file():
                return None
            digest = hashlib.sha256()
            with path.open("rb") as stream:
                for block in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(block)
            return digest.hexdigest().upper()

        dll_path = Path(getattr(dll, "_name", get_native_dll_path())).resolve()
        layout_path_value = gui_runtime_snapshot.get("layout_path")
        fit_path_value = gui_runtime_snapshot.get("fit_path")
        indicator_keys = [
            bytes(desc.key).split(b"\0", 1)[0].decode("utf-8", errors="replace")
            for desc in indicators_list
        ]
        snapshot = {
            "timestamp": datetime.now().astimezone().isoformat(),
            "origin": gui_runtime_snapshot.get("origin"),
            "gui_process_id": os.getpid(),
            "gui_thread": threading.current_thread().name,
            "render_generation_id": gui_runtime_snapshot.get("render_generation_id"),
            "absolute_dll_path": str(dll_path),
            "dll_sha256": _sha256(dll_path),
            "backend": NvidiaBackend.NVIDIA_NATIVE_D3D11.value,
            "codec": codec,
            "codec_id": int(enc_cfg.codec),
            "quality_mode": quality_profile,
            "quality_mode_id": int(enc_cfg.quality_mode),
            "resolved_nvidia_profile": profile_name,
            "bitrate_input": str(video_bitrate),
            "bitrate_bps": int(enc_cfg.bitrate_bps),
            "ring_size": max(64, int(cfg.ring_size)),
            "ring_size_requested_in_config": int(cfg.ring_size),
            "layout_absolute_path": str(Path(layout_path_value).resolve()) if layout_path_value else None,
            "layout_sha256": _sha256(layout_path_value),
            "in_memory_layout_sha256": hashlib.sha256(
                json.dumps(layout, sort_keys=True, ensure_ascii=False, default=str).encode("utf-8")
            ).hexdigest().upper(),
            "active_indicator_count": len(indicators_list),
            "active_indicator_keys": indicator_keys,
            "source_video_paths": [str(Path(clip.path).resolve()) for clip in clips_desc],
            "fit_path": str(Path(fit_path_value).resolve()) if fit_path_value else None,
            "fit_sha256": _sha256(fit_path_value),
            "preview_enabled": bool(enable_preview),
            "preview_width": int(preview_width) if enable_preview else 0,
            "preview_height": int(preview_height) if enable_preview else 0,
            "preview_fps": float(preview_fps) if enable_preview else 0.0,
            "compression_analysis_enabled": bool(enable_compression_analysis),
            "native_exporter_function": (
                "src.ffmpeg.nvidia_native_exporter.export_nvidia_native_d3d11"
            ),
            "output_absolute_path": str(output_final_path),
            "start_frame": int(start_frame),
            "requested_max_frames": max_frames,
            "resolved_export_frames": int(export_frames),
            "native_config": {
                "width": int(cfg.width),
                "height": int(cfg.height),
                "fps_num": int(cfg.fps_num),
                "fps_den": int(cfg.fps_den),
                "ring_size_requested": int(cfg.ring_size),
                "ring_size_effective_native_minimum": max(64, int(cfg.ring_size)),
                "bit_depth": int(cfg.bit_depth),
                "preset_p1_to_p7": int(cfg.preset_p1_to_p7),
                "tuning_info": int(cfg.tuning_info),
                "async_nvenc": int(cfg.async_nvenc),
                "enable_debug_layer": int(cfg.enable_debug_layer),
                "encoder_config": {
                    "codec": int(enc_cfg.codec),
                    "quality_mode": int(enc_cfg.quality_mode),
                    "bit_depth": int(enc_cfg.bit_depth),
                    "bitrate_bps": int(enc_cfg.bitrate_bps),
                    "max_bitrate_bps": int(enc_cfg.max_bitrate_bps),
                    "vbv_size_bits": int(enc_cfg.vbv_size_bits),
                    "gop_length": int(enc_cfg.gop_length),
                    "b_frames": int(enc_cfg.b_frames),
                    "multipass": int(enc_cfg.multipass),
                    "enable_lookahead": int(enc_cfg.enable_lookahead),
                    "lookahead_depth": int(enc_cfg.lookahead_depth),
                    "enable_aq": int(enc_cfg.enable_aq),
                    "aq_strength": int(enc_cfg.aq_strength),
                    "enable_temporal_aq": int(enc_cfg.enable_temporal_aq),
                    "enable_compression_analysis": int(enc_cfg.enable_compression_analysis),
                    "compression_csv_path": str(enc_cfg.compression_csv_path),
                },
            },
            "gui_options": gui_runtime_snapshot.get("gui_options", {}),
        }
        snapshot_path = Path(__file__).resolve().parents[2] / "scratch" / "gui_nvidia_runtime_snapshot.json"
        snapshot_path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = snapshot_path.with_suffix(".json.tmp")
        temp_path.write_text(
            json.dumps(snapshot, indent=2, ensure_ascii=False, default=str),
            encoding="utf-8",
        )
        temp_path.replace(snapshot_path)
        print(f"[GUI NVIDIA RUNTIME SNAPSHOT] {snapshot_path}", flush=True)

    if not dll.telem_nvenc_configure(handle, ctypes.byref(cfg)):
        dll.telem_nvenc_destroy(handle)
        proc_mux.kill()
        if audio_feeder:
            audio_feeder.stop()
        raise RuntimeError(f"Configure failed for profile {profile_name}")

    c_clips = (TelemVideoClipDesc * len(clips_desc))(*clips_desc)
    if not dll.telem_nvenc_set_video_sequence(handle, c_clips, len(clips_desc)):
        dll.telem_nvenc_destroy(handle)
        proc_mux.kill()
        if audio_feeder:
            audio_feeder.stop()
        raise RuntimeError("SetVideoSequence failed")

    # Preload map & tiles
    if map_desc:
        preload_sqlite_tiles_to_native(dll, handle, map_desc.style.map.zoom, "satellite")
    if route_points:
        route_lats = (ctypes.c_double * len(route_points))(*[float(pt[1]) for pt in route_points])
        route_lons = (ctypes.c_double * len(route_points))(*[float(pt[2]) for pt in route_points])
        dll.telem_nvenc_set_map_route(handle, route_lats, route_lons, len(route_points))

    if states:
        if isinstance(states, ctypes.Array):
            c_states = states
        else:
            c_states = (TelemFrameState * len(states))(*states)
        dll.telem_nvenc_set_telemetry(handle, c_states, len(states))

    if indicators_list:
        c_inds = (TelemIndicatorDesc * len(indicators_list))(*indicators_list)
        dll.telem_nvenc_set_indicators(handle, c_inds, len(indicators_list))

    if chart_samples_dict:
        for name, samples in chart_samples_dict.items():
            c_samples = (ctypes.c_float * len(samples))(*[float(v) for v in samples])
            dll.telem_nvenc_set_chart_samples(handle, name.encode("ascii"), c_samples, len(samples))

    # 7. Start Export
    if enable_preview:
        dll.telem_nvenc_set_preview_tap(handle, 1, int(preview_width), int(preview_height), ctypes.c_double(preview_fps))

    t_start = time.perf_counter()
    if not dll.telem_nvenc_start_export(handle, c_output_arg, start_frame, export_frames, 1):
        dll.telem_nvenc_destroy(handle)
        proc_mux.kill()
        if audio_feeder:
            audio_feeder.stop()
        raise RuntimeError("StartExport failed")

    prep_tracker.finish()

    progress = TelemProgressInfo()
    comp_stats = TelemCompressionStats()
    cancelled = False

    preview_c_buf = None
    buf_size = 0
    p_w = ctypes.c_uint32(0)
    p_h = ctypes.c_uint32(0)
    p_frame = ctypes.c_uint32(0)
    p_pts = ctypes.c_double(0.0)
    if enable_preview and on_preview_frame:
        buf_size = max(1920 * 1080 * 4, int(preview_width) * int(preview_height) * 4)
        preview_raw = bytearray(buf_size)
        preview_c_buf = (ctypes.c_char * buf_size).from_buffer(preview_raw)

    try:
        while True:
            # Check cancellation
            if cancel_event is not None and cancel_event.is_set():
                cancelled = True
                dll.telem_nvenc_cancel(handle)
                break

            dll.telem_nvenc_get_progress(handle, ctypes.byref(progress))
            cur_completed = progress.completed_frames
            cur_video_time_s = cur_completed * fps_den / float(fps_num)

            if audio_feeder:
                audio_feeder.update_video_time(cur_video_time_s)

            hud_state: Dict[str, Any] = {
                "phase": "render",
                "backend": f"NVIDIA_NATIVE_{profile_name}",
                "role": "gpu",
                "fps": progress.current_fps,
                "frame_done": cur_completed,
                "frame_total": export_frames,
                "global_pct": 10.0 + (88.0 * cur_completed / export_frames) if export_frames else 10.0,
            }

            if enable_compression_analysis:
                dll.telem_nvenc_get_compression_stats(handle, ctypes.byref(comp_stats))
                hud_state["compression_active"] = bool(comp_stats.is_active)
                hud_state["is_av1"] = bool(comp_stats.is_av1)
                hud_state["current_qp"] = comp_stats.current_qp
                hud_state["mean_qp"] = comp_stats.mean_qp
                hud_state["p90_qp"] = comp_stats.p90_qp
                hud_state["bitrate_mbps"] = comp_stats.average_bitrate_mbps

            if on_render_progress:
                on_render_progress(
                    cur_completed,
                    export_frames,
                    time.perf_counter() - t_start,
                    progress.current_fps,
                    hud_state,
                )

            if progress_cb:
                pct = int(round((100.0 * cur_completed / export_frames))) if export_frames else 0
                progress_cb(pct, f"Renderowanie ({profile_name}): {cur_completed}/{export_frames}")

            if enable_preview and on_preview_frame and preview_c_buf:
                res_prev = dll.telem_nvenc_poll_preview_frame(
                    handle,
                    preview_c_buf,
                    buf_size,
                    ctypes.byref(p_w),
                    ctypes.byref(p_h),
                    ctypes.byref(p_frame),
                    ctypes.byref(p_pts),
                )
                if res_prev:
                    w = p_w.value
                    h = p_h.value
                    stride = w * 4
                    frame_bytes = bytes(preview_raw[:stride * h])
                    try:
                        on_preview_frame(frame_bytes, w, h, stride, p_frame.value, p_pts.value)
                    except Exception:
                        pass

            if progress.is_finished or progress.is_cancelled:
                break

            time.sleep(0.05)

        # 8. Wait Completion & Muxer Termination
        if on_render_progress and not cancelled:
            on_render_progress(
                export_frames,
                export_frames,
                time.perf_counter() - t_start,
                progress.current_fps,
                {
                    "phase": "finalize",
                    "global_pct": 98.5,
                    "finalize_stage": "Finalizowanie kontenera MP4...",
                    "backend": f"NVIDIA_NATIVE_{profile_name}",
                    "compression_active": bool(comp_stats.is_active) if enable_compression_analysis else False,
                    "is_av1": bool(comp_stats.is_av1) if enable_compression_analysis else False,
                    "current_qp": comp_stats.current_qp if enable_compression_analysis else 0,
                    "mean_qp": comp_stats.mean_qp if enable_compression_analysis else 0.0,
                    "p90_qp": comp_stats.p90_qp if enable_compression_analysis else 0.0,
                    "bitrate_mbps": comp_stats.average_bitrate_mbps if enable_compression_analysis else 0.0,
                },
            )

        if not cancelled:
            dll.telem_nvenc_wait_completion(handle, 10000)
        else:
            dll.telem_nvenc_wait_completion(handle, 1000)

    finally:
        if audio_feeder:
            audio_feeder.stop()
            audio_feeder.join(timeout=3.0)

        # Close video pipe write handle so FFmpeg sees EOF on video
        if h_write_v.value:
            kernel32.CloseHandle(h_write_v)

        try:
            proc_mux.wait(timeout=10.0 if not cancelled else 2.0)
        except subprocess.TimeoutExpired:
            proc_mux.kill()

        dll.telem_nvenc_destroy(handle)

    if cancelled:
        if output_tmp_path.exists():
            output_tmp_path.unlink()
        return False

    # 9. Atomic Rename & Terminal Progress
    if output_tmp_path.exists() and output_tmp_path.stat().st_size > 0:
        output_tmp_path.replace(output_final_path)
    else:
        err_details = "\n".join(list(mux_stderr_lines)[-15:])
        raise RuntimeError(f"Natywny eksport zakończony, ale plik wyjściowy jest pusty. FFmpeg stderr:\n{err_details}")

    if on_render_progress:
        final_hud_state = {
            "phase": "finalize",
            "global_pct": 100.0,
            "finalize_stage": "Gotowe",
            "backend": f"NVIDIA_NATIVE_{profile_name}",
            "compression_active": bool(comp_stats.is_active) if enable_compression_analysis else False,
            "is_av1": bool(comp_stats.is_av1) if enable_compression_analysis else False,
            "current_qp": comp_stats.current_qp if enable_compression_analysis else 0,
            "mean_qp": comp_stats.mean_qp if enable_compression_analysis else 0.0,
            "p90_qp": comp_stats.p90_qp if enable_compression_analysis else 0.0,
            "bitrate_mbps": comp_stats.average_bitrate_mbps if enable_compression_analysis else 0.0,
        }
        on_render_progress(
            export_frames,
            export_frames,
            time.perf_counter() - t_start,
            progress.current_fps,
            final_hud_state,
        )

    if progress_cb:
        progress_cb(100, "Eksport zakończony pomyślnie.")

    return True
