"""Overlay renderer – re-exports from the `indicators` package.

Everything has been migrated to `src/indicators/` for better organisation.
This module exists for backwards compatibility – all existing `from
src.overlay_renderer import ...` statements continue to work.
"""

from __future__ import annotations

from src.indicators.compositor import compose_overlay, render_preview
from src.indicators.dispatcher import render_value_indicator
from src.indicators.chart_builder import build_chart_data
from src.indicators.frame_data import prepare_overlay_frame_data
from src.indicators.custom_text import render_custom_text
from src.indicators.rotated_paste import rotated_paste
from src.indicators.time_block import render_time_block
from src.indicators.time_display import render_time_display
from src.indicators.chart_utils import generate_history_chart
from src.indicators.text import _render_text_indicator
from src.indicators.bar import _render_bar_indicator
from src.indicators.gauge import _render_gauge_indicator
from src.indicators.chart import _render_chart_indicator
from src.indicators.segment_bar import _render_segment_bar_indicator
from src.indicators.static_map import _render_static_map_indicator
from src.indicators.moving_map import _render_moving_map_indicator
from src.indicators.helpers import (
    FONT_CACHE,
    _STATIC_CACHE,
    _parse_marker_color,
    _static_cache_key,
    load_font,
    load_font_cache_small,
    parse_hex_color,
    s,
)
