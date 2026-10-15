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
    ("battery",          "bar",   12.0),
    ("solar",            "bar",   12.0),
    ("gopro_battery",    "bar",   12.0),
    ("slope",            "bar",   20.0),
    ("lean",             "lean",  14.0),
]


# ── Default source per indicator key (exact match) ─────────────────────────
DEFAULT_SOURCE_MAP: dict[str, str] = {
    "hr_text":     "gpx",
    "cad_text":    "gpx",
    "power_text":  "gpx",
    "atemp_text":  "gpx",
    "battery_text":"gpx",
    "compass":     "gpmf",
    "slope_text":  "gpmf",
    "lean_indicator": "gpmf",
}


# ── Chart colour per key (matched by substring) ────────────────────────────
CHART_COLOR_RULES: list[tuple[str, tuple[int, int, int]]] = [
    ("speed", (255, 50, 50)),
    ("cad",   (255, 50, 50)),
    ("alt",   (50, 200, 50)),
    ("dist",  (50, 150, 255)),
    ("power", (255, 200, 50)),
    ("curvpower", (255, 200, 50)),  # 5X: was matched by "power" as a mid-token substring
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
    "cad_text", "battery_text", "compass", "slope_text", "track_map",
    "time_display",
})


# ── Indicator key → data-field helpers ─────────────────────────────────────
# These are used by _get_indicator_range() in controller.py

# ETAP 5X: rule patterns match only from the start of an ``_``-separated token
# (``alt`` → ``enhanced_altitude``, ``cad`` → ``cadence``), never from the
# middle of one.  Short abbreviations listed here must equal a whole token,
# so ``hr`` matches ``hr_text`` / ``fit_hr`` but not ``fit_hrv`` or
# ``threshold``.
WHOLE_TOKEN_PATTERNS: frozenset[str] = frozenset({"hr"})


def key_matches_pattern(key_lower: str, pattern: str) -> bool:
    """True when ``pattern`` starts at a token boundary of ``key_lower``."""
    start = 0
    while True:
        idx = key_lower.find(pattern, start)
        if idx < 0:
            return False
        if idx == 0 or key_lower[idx - 1] == "_":
            end = idx + len(pattern)
            if pattern not in WHOLE_TOKEN_PATTERNS or end == len(key_lower) or key_lower[end] == "_":
                return True
        start = idx + 1


def get_form_for_key(key: str) -> tuple[str, dict]:
    """Return (form, kwargs_override) for the given indicator key.

    Used only for defaults of a newly created indicator; a ``form`` stored in
    the layout always wins at render time.
    """
    key_lower = key.lower()
    for pattern, form, size in DEFAULT_FORM_RULES:
        if key_matches_pattern(key_lower, pattern):
            overrides: dict = {"form": form, "size": size}
            if pattern in ("battery", "solar", "gopro_battery"):
                overrides["bar_style"] = "segments"
                overrides["segments"] = 20
            elif pattern == "slope":
                overrides["bar_style"] = "slope"
            return form, overrides
    return "text", {}


def get_chart_color(key: str) -> tuple[int, int, int]:
    """Return the line colour for a chart indicator."""
    key_lower = key.lower()
    for pattern, color in CHART_COLOR_RULES:
        if key_matches_pattern(key_lower, pattern):
            return color
    return (200, 200, 200)
