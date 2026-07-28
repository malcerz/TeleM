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
        # Gauge-specific
        ("start_angle", "int", 0, 360, 5),
        ("sweep_angle", "int", 30, 360, 5),
        ("needle_length", "float", 0.1, 2.0, 0.05),
        ("needle_width", "int", 2, 20, 1),
        ("needle_color", "color", None, None, None),
    ]


# ── Per-form field filtering ─────────────────────────────────────────────────

# ── Built-in indicator definitions ───────────────────────────────────────────

BUILTIN_FIELDS: dict[str, list[tuple]] = {
    "time_block": get_common_schema() + [
        ("font_label", "float", 0.006, 0.03, 0.001),
        ("font_date", "float", 0.008, 0.05, 0.001),
        ("font_time", "float", 0.008, 0.05, 0.001),
    ],
    "time_display": get_common_schema() + [
        ("font_size", "float", 0.008, 0.08, 0.001),
        ("show_date", "bool", None, None, None),
        ("show_time", "bool", None, None, None),
        ("show_elapsed", "bool", None, None, None),
        ("show_avg_speed", "bool", None, None, None),
        ("show_date_label", "bool", None, None, None),
        ("date_label", "text", None, None, None),
        ("show_time_label", "bool", None, None, None),
        ("time_label", "text", None, None, None),
        ("show_elapsed_label", "bool", None, None, None),
        ("elapsed_label", "text", None, None, None),
        ("show_avg_speed_label", "bool", None, None, None),
        ("avg_speed_label", "text", None, None, None),
        ("date_font_size", "float", 0.008, 0.08, 0.001),
        ("time_font_size", "float", 0.008, 0.08, 0.001),
        ("elapsed_font_size", "float", 0.008, 0.08, 0.001),
        ("avg_speed_font_size", "float", 0.008, 0.08, 0.001),
        ("date_color", "color", None, None, None),
        ("time_color", "color", None, None, None),
        ("elapsed_color", "color", None, None, None),
        ("avg_speed_color", "color", None, None, None),
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
             "voyager_all", "voyager_nolabels", "satellite"],
         None, None),
        ("marker_size", "int", 3, 20, 1),
        ("marker_color", "color", None, None, None),
    ],
}
