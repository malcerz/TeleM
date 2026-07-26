"""Indicator rendering package — per-form renderers, helpers, and registries.

This package replaces the monolithic ``overlay_renderer.py`` by splitting
rendering logic into single-responsibility modules:

- ``registry.py`` — form rules, colour rules, hardcoded keys
- ``helpers.py`` — shared utilities (font cache, colour parsing, scaling)
- ``chart_utils.py`` — ``generate_history_chart()``
- ``rotated_paste.py`` — ``rotated_paste()``
- ``custom_text.py`` — ``render_custom_text()``
- ``time_block.py`` — ``render_time_block()``
- ``text.py`` — ``_render_text_indicator()``
- ``bar.py`` — ``_render_bar_indicator()``
- ``gauge.py`` — ``_render_gauge_indicator()``
- ``chart.py`` — ``_render_chart_indicator()``
- ``segment_bar.py`` — ``_render_segment_bar_indicator()``
- ``static_map.py`` — ``_render_static_map_indicator()``
- ``moving_map.py`` — ``_render_moving_map_indicator()``
- ``dispatcher.py`` — ``render_value_indicator()``
- ``chart_builder.py`` — ``build_chart_data()``
- ``frame_data.py`` — ``prepare_overlay_frame_data()``
- ``compositor.py`` — ``compose_overlay()`` + ``render_preview()``

Backwards compatibility is maintained by re-exporting all public symbols
from ``src.overlay_renderer``, which imports from this package.
"""

from __future__ import annotations

# Re-export registry symbols (these were the original `src/indicators.py`)
from .registry import (
    CHART_COLOR_RULES,
    DEFAULT_FORM_RULES,
    DEFAULT_SOURCE_MAP,
    HARDCODED_KEYS,
    SEGMENT_BAR_DEFAULT_GRADIENT,
    get_chart_color,
    get_form_for_key,
)

# Re-export shared helpers (used by overlay_renderer.py)
from .helpers import (
    FONT_CACHE,
    _STATIC_CACHE,
    _parse_marker_color,
    _static_cache_key,
    load_font,
    load_font_cache_small,
    parse_hex_color,
    s,
)

# Chart utilities
from .chart_utils import generate_history_chart

# Single-indicator rendering
from .custom_text import render_custom_text
from .rotated_paste import rotated_paste
from .time_block import render_time_block

# Per-form renderers
from .text import _render_text_indicator
from .bar import _render_bar_indicator
from .gauge import _render_gauge_indicator
from .chart import _render_chart_indicator
from .segment_bar import _render_segment_bar_indicator
from .static_map import _render_static_map_indicator
from .moving_map import _render_moving_map_indicator

# Dispatcher
from .dispatcher import render_value_indicator

# Data preparation
from .chart_builder import build_chart_data
from .frame_data import prepare_overlay_frame_data

# Compositor
from .compositor import compose_overlay, render_preview
