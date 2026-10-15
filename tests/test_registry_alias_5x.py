"""ETAP 5X: indicator form/colour rules match at token boundaries only."""
import json
import subprocess
import sys
import types
from pathlib import Path

import pytest

from src.indicators import registry

ROOT = Path(__file__).resolve().parents[1]


def _legacy_registry():
    """registry.py as of 8af7934 (substring matching), loaded in isolation."""
    src = subprocess.check_output(["git", "show", "8af7934:src/indicators/registry.py"], cwd=ROOT, text=True)
    mod = types.ModuleType("legacy_registry")
    exec(compile(src, "legacy_registry", "exec"), mod.__dict__)
    return mod


@pytest.mark.parametrize("key, form", [
    ("hr_text", "chart"),
    ("fit_hr_text", "chart"),
    ("fit_heart_rate_text", "chart"),
    ("fit_hrv_text", "text"),            # was chart via "hr" inside "hrv"
    ("fit_threshold_heart_rate_text", "chart"),
    ("fit_cadence_text", "chart"),
    ("fit_fractional_cadence_text", "chart"),
    ("alt_text", "bar"),
    ("fit_enhanced_altitude_text", "bar"),
    ("fit_salt_text", "text"),           # was bar via "alt" inside "salt"
    ("speed_text", "gauge"),
    ("fit_enhanced_speed_text", "gauge"),
    ("fit_passing_speedabs_text", "gauge"),
    ("fit_power_text", "chart"),
    ("fit_curVpower_text", "chart"),
    ("fit_garmin_battery_percent_text", "bar"),
    ("fit_solar_text", "bar"),
    ("slope_text", "bar"),
    ("lean_indicator", "lean"),
    ("fit_temperature_text", "text"),
    ("compass", "text"),
    ("fit_unknown_field_text", "text"),
])
def test_form_rules(key, form):
    assert registry.get_form_for_key(key)[0] == form


def test_existing_layout_keys_unchanged():
    legacy = _legacy_registry()
    layout = json.loads((ROOT / "def_layout.json").read_text(encoding="utf-8-sig"))
    for key in layout["indicators"]:
        assert registry.get_form_for_key(key) == legacy.get_form_for_key(key), key
        assert registry.get_chart_color(key) == legacy.get_chart_color(key), key


def test_hr_colour_not_taken_by_hrv():
    assert registry.get_chart_color("fit_hr_text") == (255, 50, 150)
    assert registry.get_chart_color("fit_hrv_text") == (200, 200, 200)
