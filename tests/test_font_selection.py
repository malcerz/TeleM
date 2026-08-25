from __future__ import annotations

import os
from pathlib import Path
import json
import numpy as np
from PIL import ImageFont

from src.gui.qt.models import get_schema_for_form, time_display_indicator_fields
from src.indicators.helpers import (
    FONT_CACHE,
    _FONT_PATH_CACHE,
    indicator_font_path,
    load_font,
    resolve_indicator_font_path,
    resolve_font_file,
)
from src.indicators.compositor import compose_overlay


ARIAL = Path(r"C:\Windows\Fonts\arial.ttf")
COURIER = Path(r"C:\Windows\Fonts\cour.ttf")


def test_missing_font_property_preserves_existing_default() -> None:
    assert resolve_indicator_font_path(None, str(ARIAL)) == str(ARIAL)
    assert resolve_indicator_font_path("", str(ARIAL)) == str(ARIAL)


def test_absolute_relative_and_invalid_font_paths(tmp_path: Path) -> None:
    relative_font = tmp_path / "local.ttf"
    relative_font.write_bytes(COURIER.read_bytes())
    assert resolve_indicator_font_path(relative_font, str(ARIAL)) == str(relative_font.resolve())
    assert resolve_indicator_font_path("local.ttf", str(ARIAL), tmp_path) == str(relative_font.resolve())
    assert resolve_indicator_font_path("missing.ttf", str(ARIAL), tmp_path) == str(ARIAL)
    assert resolve_indicator_font_path("font.txt", str(ARIAL), tmp_path) == str(ARIAL)
    broken = tmp_path / "broken.ttf"
    broken.write_bytes(b"not a font")
    assert resolve_indicator_font_path(broken, str(ARIAL)) == str(ARIAL)


def test_per_indicator_font_is_independent() -> None:
    layout = {
        "indicators": {
            "speed_text": {"font": str(COURIER)},
            "hr_text": {},
        }
    }
    assert indicator_font_path(layout, "speed_text", str(ARIAL)) == str(COURIER.resolve())
    assert indicator_font_path(layout, "hr_text", str(ARIAL)) == str(ARIAL)


def test_font_cache_is_keyed_by_path_and_size() -> None:
    FONT_CACHE.clear()
    arial = load_font(str(ARIAL), 32)
    courier = load_font(str(COURIER), 32)
    assert arial is not courier
    assert (str(ARIAL), 32) in FONT_CACHE
    assert (str(COURIER), 32) in FONT_CACHE


def test_gui_schemas_expose_one_canonical_font_property() -> None:
    for form in ("text", "gauge", "compass", "bar", "chart", "segment_bar"):
        fields = get_schema_for_form(form)
        assert [field.name for field in fields].count("font") == 1
        assert next(field for field in fields if field.name == "font").field_type == "font"
    assert [field.name for field in time_display_indicator_fields()].count("font") == 1


def test_font_property_json_roundtrip(tmp_path: Path) -> None:
    source = {"indicators": {"speed_text": {"font": str(COURIER)}}}
    path = tmp_path / "font-layout.json"
    path.write_text(json.dumps(source), encoding="utf-8")
    loaded = json.loads(path.read_text(encoding="utf-8"))
    assert loaded["indicators"]["speed_text"]["font"] == str(COURIER)


def test_system_font_family_resolution_windows() -> None:
    """Verify that Windows family names (e.g. Comic Sans, Arial) resolve to valid font files."""
    if os.name != "nt":
        return
    resolved_comic = resolve_indicator_font_path("Comic Sans", "")
    assert Path(resolved_comic).is_file()
    assert Path(resolved_comic).suffix.lower() in {".ttf", ".otf", ".ttc"}

    resolved_arial = resolve_indicator_font_path("Arial", "")
    assert Path(resolved_arial).is_file()


def test_unknown_font_graceful_fallback() -> None:
    """Verify unknown font names fall back to default without exception."""
    res, reason = resolve_font_file("__FONT_DOES_NOT_EXIST__", default="FALLBACK")
    assert res == "FALLBACK"
    assert reason is not None
    assert "not found" in reason


def test_font_invalidation_and_distinct_raster() -> None:
    """Verify changing font dynamically changes rendered raster output."""
    if not ARIAL.exists() or not COURIER.exists():
        return

    def render_sample(font_prop: str):
        layout = {
            "indicators": {
                "speed_text": {
                    "font": font_prop, "enabled": True, "form": "text",
                    "x": 50.0, "y": 50.0, "font_size": 4.0, "size": 30.0,
                    "show_value": True, "show_units": True, "unit": "km/h",
                }
            }
        }
        return np.array(compose_overlay(
            400, 200, layout, font_path="",
            date_text="", time_text="",
            speed_value=28.6, distance_m=1000.0,
            reuse_canvas=False,
        ))

    img_arial1 = render_sample(str(ARIAL))
    img_cour = render_sample(str(COURIER))
    img_arial2 = render_sample(str(ARIAL))

    # Arial and Courier must be visually distinct
    assert not np.array_equal(img_arial1, img_cour)
    # Reverting to Arial must produce exact match
    assert np.array_equal(img_arial1, img_arial2)
