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
        ("x", "float", 0.0, 100.0, 0.1),
        ("y", "float", 0.0, 100.0, 0.1),
        ("rotation", "choice", [0, 90], None, None),
    ]


def get_value_schema() -> list[tuple]:
    """Return the schema fields for value indicators (text/gauge/bar/chart)."""
    return get_common_schema() + [
        ("form", "choice", ["text", "gauge", "bar", "chart", "segment_bar"], None, None),
        ("font_size", "float", 0.5, 10.0, 0.1),
        ("size", "float", 1.0, 50.0, 0.1),
        ("thickness", "int", 1, 10, 1),
        ("min_val", "float", 0.0, 1000.0, 1.0),
        ("max_val", "float", 1.0, 10000.0, 1.0),
        ("ticks", "int", 0, 20, 1),
        ("show_value", "bool", None, None, None),
        ("value_offset_x", "float", -30.0, 30.0, 0.1),
        ("value_offset_y", "float", -30.0, 30.0, 0.1),
        ("chart_color", "color", None, None, None),
        ("fill_color", "color", None, None, None),
        ("fill_alpha", "int", 0, 255, 5),
        ("chart_time_scope", "choice", ["activity", "video"], None, None),
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
        ("font_label", "float", 0.6, 3.0, 0.1),
        ("font_date", "float", 0.8, 5.0, 0.1),
        ("font_time", "float", 0.8, 5.0, 0.1),
    ],
    "time_display": get_common_schema() + [
        ("font_size", "float", 0.8, 8.0, 0.1),
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
        ("date_font_size", "float", 0.8, 8.0, 0.1),
        ("time_font_size", "float", 0.8, 8.0, 0.1),
        ("elapsed_font_size", "float", 0.8, 8.0, 0.1),
        ("avg_speed_font_size", "float", 0.8, 8.0, 0.1),
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
        ("range_label_offset_x", "float", -20.0, 20.0, 0.1),
        ("range_label_offset_y", "float", -20.0, 20.0, 0.1),
        ("range_label_spread_x", "float", -20.0, 20.0, 0.1),
    ],
    "dist_text":    get_value_schema() + [
        ("source", "choice", TELEMETRY_SOURCES, None, None),
    ],
    "alt_visual": get_value_schema() + [
        ("source", "choice", TELEMETRY_SOURCES, None, None),
        ("show_range_labels", "bool", None, None, None),
        ("range_label_offset_x", "float", -20.0, 20.0, 0.1),
        ("range_label_offset_y", "float", -20.0, 20.0, 0.1),
        ("range_label_spread_x", "float", -20.0, 20.0, 0.1),
    ],
    "alt_text":    get_value_schema() + [
        ("source", "choice", TELEMETRY_SOURCES, None, None),
    ],
    "iso_text":    get_value_schema() + [("source", "choice", TELEMETRY_SOURCES, None, None)],
    "exposure_text": get_value_schema() + [("source", "choice", TELEMETRY_SOURCES, None, None)],
    "temp_text":     get_value_schema() + [("source", "choice", TELEMETRY_SOURCES, None, None)],
    "power_text":    get_value_schema() + [("source", "choice", TELEMETRY_SOURCES, None, None)],
    "atemp_text":    get_value_schema() + [("source", "choice", TELEMETRY_SOURCES, None, None)],
    "hr_text":       get_value_schema() + [("source", "choice", TELEMETRY_SOURCES, None, None)],
    "cad_text":      get_value_schema() + [("source", "choice", TELEMETRY_SOURCES, None, None)],
    "battery_text":  get_value_schema() + [("source", "choice", TELEMETRY_SOURCES, None, None)],
    "track_map":     get_common_schema() + [
        ("source", "choice", TELEMETRY_SOURCES, None, None),
        ("size", "float", 5.0, 40.0, 0.1),
        ("zoom", "int", 10, 20, 1),
        ("map_style", "choice",
            ["light_all", "light_nolabels", "dark_all", "dark_nolabels",
             "voyager_all", "voyager_nolabels", "satellite"],
         None, None),
        ("marker_size", "int", 3, 20, 1),
        ("marker_color", "color", None, None, None),
    ],
}
