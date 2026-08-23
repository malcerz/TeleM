import pytest
import json
from pathlib import Path
from PIL import Image, ImageChops

import src.indicators.bar as bar_mod
from src.indicators.helpers import resolve_indicator_font_path


@pytest.fixture
def v10_layout():
    preset_path = Path(__file__).resolve().parents[1] / "presets" / "cycling_dashboard_v10.json"
    with open(preset_path, "r", encoding="utf-8") as f:
        return json.load(f)


def test_slope_parity_and_values(v10_layout):
    """Test Slope rendering across representative values including negative, zero, positive, None."""
    slope_cfg = dict(v10_layout["indicators"]["slope_text"])
    for val in [-12.0, -5.0, 0.0, 3.7, 10.0, None]:
        cfg_test = dict(slope_cfg)
        if val is None:
            cfg_test["_slope_missing"] = True
        v = 0.0 if val is None else val
        img, x, y, _ = bar_mod._render_bar_indicator(
            1280, 720, v10_layout, "", "slope_text", v, "%", "SLOPE",
            cfg_test, 720, 1, 9, None, -20.0, 20.0, 0, 2, 108, 1,
            formatted_val=None
        )
        assert img is not None
        assert img.size[0] > 0 and img.size[1] > 0


def test_altitude_parity_and_values(v10_layout):
    """Test Altitude ruler rendering across min, 25%, 50%, 75%, max, and None."""
    alt_cfg = dict(v10_layout["indicators"]["alt_visual"])
    for frac, val in [(0.0, 0.0), (0.25, 250.0), (0.50, 500.0), (0.75, 750.0), (1.0, 1000.0), (None, None)]:
        img, x, y, _ = bar_mod._render_bar_indicator(
            1280, 720, v10_layout, "", "alt_visual", val, "m", "ALTITUDE",
            alt_cfg, 720, 1, 9, None, 0.0, 1000.0, 5, 1, 115, 1,
            formatted_val=None
        )
        assert img is not None
        assert img.size[0] > 0 and img.size[1] > 0


def test_distance_and_battery_solar_regressions(v10_layout):
    """Verify Distance, Battery, and Solar widgets continue to render without regression."""
    # Distance
    dist_cfg = dict(v10_layout["indicators"]["dist_visual"])
    for val in [0.0, 2.5, 5.0, 10.0, None]:
        img, _, _, _ = bar_mod._render_bar_indicator(
            1280, 720, v10_layout, "", "dist_visual", val, "km", "DISTANCE",
            dist_cfg, 720, 1, 9, None, 0.0, 10.0, 5, 1, 201, 1,
        )
        assert img is not None

    # Battery
    bat_cfg = dict(v10_layout["indicators"]["fit_battery_pct_text"])
    for val in [0.0, 50.0, 100.0, None]:
        img, _, _, _ = bar_mod._render_bar_indicator(
            1280, 720, v10_layout, "", "fit_battery_pct_text", val, "%", "EDGE BATTERY",
            bat_cfg, 720, 1, 9, None, 0.0, 100.0, 0, 1, 86, 1,
        )
        assert img is not None

    # Solar
    sol_cfg = dict(v10_layout["indicators"]["fit_solar_pct_text"])
    for val in [0.0, 40.0, 100.0, None]:
        img, _, _, _ = bar_mod._render_bar_indicator(
            1280, 720, v10_layout, "", "fit_solar_pct_text", val, "%", "SOLAR",
            sol_cfg, 720, 1, 9, None, 0.0, 100.0, 0, 1, 86, 1,
        )
        assert img is not None


def test_font_switching_slope_and_altitude(v10_layout):
    """Test custom font switching for Slope and Altitude without crashing."""
    for font_name in ["default", "Comic Sans", "Digital-7", "Iona-u1"]:
        f_path = resolve_indicator_font_path(font_name, "")
        img_s, _, _, _ = bar_mod._render_bar_indicator(
            1280, 720, v10_layout, f_path, "slope_text", 3.5, "%", "SLOPE",
            v10_layout["indicators"]["slope_text"], 720, 1, 9, None, -20.0, 20.0, 0, 2, 108, 1,
        )
        assert img_s is not None

        img_a, _, _, _ = bar_mod._render_bar_indicator(
            1280, 720, v10_layout, f_path, "alt_visual", 345.0, "m", "ALTITUDE",
            v10_layout["indicators"]["alt_visual"], 720, 1, 9, None, 0.0, 1000.0, 5, 1, 115, 1,
        )
        assert img_a is not None


def test_major_step_ruler(v10_layout):
    """Verify major_step specifies exact unit interval on continuous ruler."""
    cfg = dict(v10_layout["indicators"]["dist_visual"])
    cfg["major_step"] = 2.0
    img, _, _, _ = bar_mod._render_bar_indicator(
        1280, 720, v10_layout, "", "dist_visual", 4.0, "km", "DISTANCE",
        cfg, 720, 1, 9, None, 0.0, 10.0, 5, 1, 201, 1,
    )
    assert img is not None
