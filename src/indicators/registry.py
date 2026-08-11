"""Indicator registry — default forms, sources, colors, and configuration.

This module consolidates all per-key indicator configuration so that both
``overlay_renderer.py`` (rendering) and ``controller.py`` (creation) read
from the same source.  No more drift.
"""

from __future__ import annotations


# ── Default form per indicator key (matched by substring) ──────────────────
# (priority: first match wins)
# Each entry is (substring_to_match, form_name, size_multiplier)
DEFAULT_FORM_RULES: list[tuple[str, str, float]] = [
    ("passing_speedabs", "gauge", 12.0),
    ("passing_speed",    "gauge", 12.0),
    ("speed",            "gauge", 12.0),
    ("cad",              "chart", 30.0),
    ("heart_rate",       "chart", 30.0),
    ("hr",               "chart", 30.0),
    ("power",            "chart", 30.0),
    ("curvpower",        "chart", 30.0),
    ("alt",              "bar",   15.0),
    ("distance",         "bar",   15.0),
    ("dist",             "bar",   15.0),
    ("battery",          "segment_bar", 12.0),
    ("solar",            "segment_bar", 12.0),
    ("gopro_battery",    "segment_bar", 12.0),
]


# ── Default source per indicator key (exact match) ─────────────────────────
DEFAULT_SOURCE_MAP: dict[str, str] = {
    "hr_text":     "gpx",
    "cad_text":    "gpx",
    "power_text":  "gpx",
    "atemp_text":  "gpx",
    "battery_text":"gpx",
}


# ── Chart colour per key (matched by substring) ────────────────────────────
CHART_COLOR_RULES: list[tuple[str, tuple[int, int, int]]] = [
    ("speed", (255, 50, 50)),
    ("cad",   (255, 50, 50)),
    ("alt",   (50, 200, 50)),
    ("dist",  (50, 150, 255)),
    ("power", (255, 200, 50)),
    ("hr",    (255, 50, 150)),
    ("battery", (50, 255, 50)),
]


# ── Segment-bar default gradient ──────────────────────────────────────────
SEGMENT_BAR_DEFAULT_GRADIENT = ["#00FF00", "#FFFF00", "#FF0000"]


# ── Hardcoded keys (never go to extra_indicators) ──────────────────────────
HARDCODED_KEYS: frozenset[str] = frozenset({
    "speed_visual", "speed_text", "dist_visual", "dist_text",
    "alt_visual", "alt_text", "iso_text", "exposure_text",
    "temp_text", "power_text", "atemp_text", "hr_text",
    "cad_text", "battery_text", "track_map", "time_block",
    "time_display",
})


# ── Indicator key → data-field helpers ─────────────────────────────────────
# These are used by _get_indicator_range() in controller.py

def get_form_for_key(key: str) -> tuple[str, dict]:
    """Return (form, kwargs_override) for the given indicator key."""
    key_lower = key.lower()
    for pattern, form, size in DEFAULT_FORM_RULES:
        if pattern in key_lower:
            overrides: dict = {"form": form, "size": size}
            if form == "segment_bar":
                overrides["segments"] = 20
            return form, overrides
    return "text", {}


def get_chart_color(key: str) -> tuple[int, int, int]:
    """Return the line colour for a chart indicator."""
    key_lower = key.lower()
    for pattern, color in CHART_COLOR_RULES:
        if pattern in key_lower:
            return color
    return (200, 200, 200)
