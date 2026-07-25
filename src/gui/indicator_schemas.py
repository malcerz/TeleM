"""Indicator type definitions – schemas, field sets, and built-in indicator configs.

This module contains all data definitions for HUD telemetry indicators,
separated from the GUI application logic.
"""

from __future__ import annotations

# ── Constants ────────────────────────────────────────────────────────────────

# Available telemetry sources for indicators (extensible: add 'fit', etc.)
TELEMETRY_SOURCES: list[str] = ['gpmf', 'gpx', 'fit']

TELEMETRY_TAGS: list[str] = [
    '-GPSDateTime', '-GPSSpeed', '-GPSSpeed3D',
    '-SampleTime', '-TimeStamp',
    '-GPSLatitude', '-GPSLongitude', '-GPSAltitude',
    '-ISOSpeed', '-ISOSpeedRatings',
    '-CameraTemperature', '-ExposureTimes',
]


# ── Schema helpers ───────────────────────────────────────────────────────────

def get_common_schema() -> list[tuple]:
    """Return the common schema fields shared by all indicator types."""
    return [
        ("enabled", "bool", None, None, None),
        ("label", "text", None, None, None),
        ("x", "float", 0.0, 1.0, 0.001),
        ("y", "float", 0.0, 1.0, 0.001),
        ("rotation", "choice", [0, 90], None, None),
    ]


def get_value_schema() -> list[tuple]:
    """Return the schema fields for value indicators (text/gauge/bar/chart)."""
    return get_common_schema() + [
        ("form", "choice", ["text", "gauge", "bar", "chart", "segment_bar"], None, None),
        ("font_size", "float", 0.005, 0.1, 0.001),
        ("size", "float", 0.01, 0.5, 0.001),
        ("thickness", "int", 1, 10, 1),
        ("min_val", "float", 0.0, 1000.0, 1.0),
        ("max_val", "float", 1.0, 10000.0, 1.0),
        ("ticks", "int", 0, 20, 1),
        ("show_value", "bool", None, None, None),
        ("value_offset_x", "float", -0.3, 0.3, 0.001),
        ("value_offset_y", "float", -0.3, 0.3, 0.001),
        ("chart_color", "color", None, None, None),
        ("fill_color", "color", None, None, None),
        ("fill_alpha", "int", 0, 255, 5),
    ]


# ── Per-form field filtering ─────────────────────────────────────────────────

def get_segment_bar_schema() -> list[tuple]:
    """Return the schema fields for segment_bar indicators."""
    return get_common_schema() + [
        ("form", "choice", ["text", "gauge", "bar", "chart", "segment_bar"], None, None),
        ("source", "choice", TELEMETRY_SOURCES, None, None),
        ("width", "int", 250, 800, 10),
        ("height", "int", 50, 300, 5),
        ("segments", "int", 20, 100, 1),
        ("segment_gap", "int", 2, 20, 1),
        ("segment_radius", "int", 2, 20, 1),
        ("min_val", "float", 0.0, 1000.0, 1.0),
        ("max_val", "float", 100.0, 10000.0, 1.0),
        ("show_value", "bool", None, None, None),
        ("show_min", "bool", None, None, None),
        ("show_max", "bool", None, None, None),
        ("show_label", "bool", None, None, None),
        ("decimals", "int", 0, 3, 1),
        ("direction", "choice", ["horizontal", "vertical"], None, None),
        ("grow_height", "bool", None, None, None),
        ("inactive_alpha", "int", 100, 255, 5),
        ("inactive_color", "color", None, None, None),
    ]


_FORM_FIELDS: dict[str, set[str]] = {
    "text":  {"font_size", "size", "show_value", "value_offset_x", "value_offset_y"},
    "gauge": {"font_size", "size", "thickness", "min_val", "max_val", "ticks",
              "show_value", "value_offset_x", "value_offset_y"},
    "bar":   {"font_size", "size", "thickness", "min_val", "max_val", "ticks",
              "show_value", "value_offset_x", "value_offset_y",
              "show_range_labels", "range_label_offset_x", "range_label_offset_y", "range_label_spread_x"},
    "chart": {"font_size", "size", "thickness", "chart_color", "fill_color", "fill_alpha"},
    "segment_bar": {"width", "height", "segments", "segment_gap", "segment_radius",
                    "min_val", "max_val", "show_value", "show_min", "show_max",
                    "show_label", "decimals", "direction", "grow_height",
                    "inactive_alpha", "inactive_color", "source"},
    "map":        {"font_size", "size", "zoom", "map_style", "marker_size", "marker_color"},
    "static_map": {"font_size", "size", "zoom", "map_style", "marker_size", "marker_color"},
}

_ALL_FORM_FIELDS: set[str] = set().union(*_FORM_FIELDS.values()).union({"form"})


# ── Built-in indicator definitions ───────────────────────────────────────────

BUILTIN_FIELDS: dict[str, list[tuple]] = {
    "time_block": get_common_schema() + [
        ("font_label", "float", 0.006, 0.03, 0.001),
        ("font_date", "float", 0.008, 0.05, 0.001),
        ("font_time", "float", 0.008, 0.05, 0.001),
    ],
    "speed_visual": get_value_schema() + [
        ("source", "choice", TELEMETRY_SOURCES, None, None),
    ],
    "speed_text":   get_value_schema() + [
        ("source", "choice", TELEMETRY_SOURCES, None, None),
    ],
    "dist_visual": get_value_schema() + [
        ("source", "choice", TELEMETRY_SOURCES, None, None),
        ("show_range_labels", "bool", None, None, None),
        ("range_label_offset_x", "float", -0.2, 0.2, 0.001),
        ("range_label_offset_y", "float", -0.2, 0.2, 0.001),
        ("range_label_spread_x", "float", -0.2, 0.2, 0.001),
    ],
    "dist_text":    get_value_schema() + [
        ("source", "choice", TELEMETRY_SOURCES, None, None),
    ],
    "alt_visual": get_value_schema() + [
        ("source", "choice", TELEMETRY_SOURCES, None, None),
        ("show_range_labels", "bool", None, None, None),
        ("range_label_offset_x", "float", -0.2, 0.2, 0.001),
        ("range_label_offset_y", "float", -0.2, 0.2, 0.001),
        ("range_label_spread_x", "float", -0.2, 0.2, 0.001),
    ],
    "alt_text":    get_value_schema() + [
        ("source", "choice", TELEMETRY_SOURCES, None, None),
    ],
    "iso_text":    get_value_schema(),
    "exposure_text": get_value_schema(),
    "temp_text":     get_value_schema(),
    "power_text":    get_value_schema(),
    "atemp_text":    get_value_schema(),
    "hr_text":       get_value_schema(),
    "cad_text":      get_value_schema(),
    "battery_text":  get_value_schema(),
    "track_map":     get_common_schema() + [
        ("source", "choice", TELEMETRY_SOURCES, None, None),
        ("size", "float", 0.05, 0.4, 0.001),
        ("zoom", "int", 10, 20, 1),
        ("map_style", "choice",
            ["light_all", "light_nolabels", "dark_all", "dark_nolabels",
             "voyager_all", "voyager_nolabels"],
         None, None),
        ("marker_size", "int", 3, 20, 1),
        ("marker_color", "color", None, None, None),
    ],
}
