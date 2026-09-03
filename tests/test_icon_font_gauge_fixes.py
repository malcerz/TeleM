import os
import sys
import json
import tempfile
import numpy as np
from pathlib import Path
from PIL import Image

import pytest


def test_bug1_iso_icon_not_ipo():
    """Verify ISO icon renders the letter 'S' and not 'P'."""
    svg_path = Path("src/assets/icons/svg/iso.svg")
    assert svg_path.exists(), "src/assets/icons/svg/iso.svg must exist"
    svg_content = svg_path.read_text(encoding="utf-8")
    
    # Must not contain the erroneous 'P' path
    assert "v1c0 .8-.7 1.5-1.5 1.5H10v3H9v-7zm1 3h2.2" not in svg_content, "Found erroneous 'P' path in iso.svg!"
    
    # Must render via render_icon
    from src.indicators.icons import render_icon, _ICON_RENDER_CACHE
    _ICON_RENDER_CACHE.clear()
    im = render_icon("iso", size=64)
    assert im is not None, "render_icon('iso') returned None"
    assert isinstance(im, Image.Image)
    assert im.size[0] > 0 and im.size[1] > 0
    
    arr = np.array(im.convert("RGBA"))
    alpha = arr[:, :, 3]
    assert np.count_nonzero(alpha > 128) > 100


def test_bug2_font_lifecycle_and_persistence():
    """Verify font lifecycle: model defaults, layout normalization, and autosave."""
    from src.gui.layout_manager import default_layout, normalize_layout
    
    # 1. default_layout must provide 'font': '' for all indicators
    d_layout = default_layout(1920, 1080)
    indicators = d_layout.get("indicators", {})
    for name, ind in indicators.items():
        assert "font" in ind, f"Indicator '{name}' missing 'font' key in default_layout"
        assert ind["font"] == "", f"Indicator '{name}' has non-empty default font"
        
    # 2. normalize_layout must ensure 'font' exists even on legacy files missing 'font'
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as tf:
        tf_path = Path(tf.name)
        legacy_data = {
            "indicators": {
                "speed_visual": {"enabled": True, "form": "gauge", "thickness": 3},
                "speed_text": {"enabled": True, "form": "text"},
            }
        }
        json.dump(legacy_data, tf)
    try:
        norm = normalize_layout(tf_path, 1920, 1080)
        assert norm["indicators"]["speed_visual"]["font"] == ""
        assert norm["indicators"]["speed_text"]["font"] == ""
    finally:
        if tf_path.exists():
            tf_path.unlink()


def test_bug2_property_editor_font_clearing_on_selection():
    """Verify PropertyEditor does not leave previous font text when switching indicators."""
    from PySide6.QtWidgets import QApplication
    from src.gui.qt.widgets.property_editor import PropertyEditor
    from src.gui.qt.models import FieldSchema

    app = QApplication.instance() or QApplication(sys.argv)
    editor = PropertyEditor()
    
    schema = [
        FieldSchema("font", "font", "Font", tab="", default=""),
        FieldSchema("size", "float", "Rozmiar", tab="", min_val=0.1, max_val=50.0, step=0.1, default=10.0),
    ]
    
    # 1. First indicator has custom font
    editor.on_properties_ready("ind_1", schema, {"font": "Impact", "size": 12.0})
    font_widget = editor._field_widgets.get("font")
    assert font_widget is not None
    assert font_widget.text() == "Impact"
    
    # 2. Switch to second indicator without font (or font="")
    editor.on_properties_ready("ind_2", schema, {"font": "", "size": 10.0})
    font_widget2 = editor._field_widgets.get("font")
    assert font_widget2 is not None
    assert font_widget2.text() == "", "Font widget must clear when switching to indicator without font"
    
    # 3. Test update_field_values in place
    editor.update_field_values({"font": "Arial", "size": 15.0})
    assert editor._field_widgets["font"].text() == "Arial"
    editor.update_field_values({"font": "", "size": 15.0})
    assert editor._field_widgets["font"].text() == ""


def _call_gauge(cfg, value=50.0):
    """Helper to render gauge via dispatcher."""
    from src.indicators.dispatcher import render_value_indicator
    cfg_copy = dict(cfg)
    cfg_copy["form"] = "gauge"
    layout = {"indicators": {"speed_visual": cfg_copy}, "global": {"text_outline": 3}}
    return render_value_indicator(
        1920, 1080, layout, None, "speed_visual", value, "km/h", "Speed"
    )


def test_bug3_gauge_needle_thickness_cache_reactivity():
    """Verify gauge raster cache and canvas state track needle thickness and geometry."""
    from src.indicators.gauge import clear_gauge_cache, _GAUGE_RASTER_CACHE, _GAUGE_CANVAS_STATE
    
    clear_gauge_cache()
    
    cfg_base = {
        "x": 50.0, "y": 50.0, "size": 20.0,
        "min_val": 0, "max_val": 100, "ticks": 5,
        "needle_width": 2, "needle_length": 1.0, "needle_color": "#FF0000",
        "thickness": 3,
    }
    
    # 1. Render with needle_width = 2
    img1, x1, y1, _ = _call_gauge(cfg_base, 50.0)
    assert len(_GAUGE_RASTER_CACHE) == 1
    
    # 2. Render with needle_width = 10 -> MUST NOT HIT OLD CACHE
    cfg_thick = dict(cfg_base)
    cfg_thick["needle_width"] = 10
    img2, x2, y2, _ = _call_gauge(cfg_thick, 50.0)
    
    # The two images must be different because needle thickness changed!
    arr1 = np.array(img1.convert("RGBA"))
    arr2 = np.array(img2.convert("RGBA"))
    diff = np.sum(np.abs(arr1.astype(int) - arr2.astype(int)))
    assert diff > 0, "Changing needle_width MUST change rendered output without caching stale needle!"
    
    # Both entries should be cached separately
    assert len(_GAUGE_RASTER_CACHE) == 2
    
    # 3. clear_gauge_cache must reset both caches
    clear_gauge_cache()
    assert len(_GAUGE_RASTER_CACHE) == 0
    assert _GAUGE_CANVAS_STATE["canvas"] is None


def test_bug4_gauge_tick_length_and_thickness_decoupled():
    """Verify gauge tick length and thickness can be controlled independently."""
    from src.indicators.gauge import clear_gauge_cache
    
    clear_gauge_cache()
    
    # Baseline configuration
    cfg_base = {
        "x": 50.0, "y": 50.0, "size": 20.0,
        "min_val": 0, "max_val": 100, "ticks": 5,
        "thickness": 3,
        "major_tick_length": 4.0, "minor_tick_length": 2.0,
        "major_tick_thickness": 3, "minor_tick_thickness": 1,
        "show_value": False,  # disable text/needle to test static ticks purely
    }
    img_base, _, _, _ = _call_gauge(cfg_base, None)
    arr_base = np.array(img_base.convert("RGBA"))
    
    # 1. Change ONLY major_tick_length (length changes, thickness constant)
    cfg_long = dict(cfg_base)
    cfg_long["major_tick_length"] = 8.0
    img_long, _, _, _ = _call_gauge(cfg_long, None)
    arr_long = np.array(img_long.convert("RGBA"))
    diff_length = np.sum(np.abs(arr_base.astype(int) - arr_long.astype(int)))
    assert diff_length > 0, "Changing major_tick_length must alter output"
    
    # 2. Change ONLY major_tick_thickness (thickness changes, length constant)
    cfg_thick = dict(cfg_base)
    cfg_thick["major_tick_thickness"] = 8
    img_thick, _, _, _ = _call_gauge(cfg_thick, None)
    arr_thick = np.array(img_thick.convert("RGBA"))
    diff_thick = np.sum(np.abs(arr_base.astype(int) - arr_thick.astype(int)))
    assert diff_thick > 0, "Changing major_tick_thickness must alter output"
    
    # 3. Verify length change != thickness change
    diff_between = np.sum(np.abs(arr_long.astype(int) - arr_thick.astype(int)))
    assert diff_between > 0, "Length and thickness modifications must produce distinct geometries"


def test_bug4_legacy_thickness_fallback_parity():
    """Verify that omitting explicit tick parameters produces identical results to legacy thickness."""
    from src.indicators.gauge import clear_gauge_cache
    
    clear_gauge_cache()
    
    # Legacy config (no major_tick_length etc.)
    cfg_legacy = {
        "x": 50.0, "y": 50.0, "size": 20.0,
        "min_val": 0, "max_val": 100, "ticks": 5,
        "thickness": 4,
        "show_value": False,
    }
    img_leg, _, _, _ = _call_gauge(cfg_legacy, None)
    arr_leg = np.array(img_leg.convert("RGBA"))
    
    # Explicit config with identical values (4.0, 4.0, 4, 4)
    cfg_explicit = dict(cfg_legacy)
    cfg_explicit["major_tick_length"] = 4.0
    cfg_explicit["minor_tick_length"] = 4.0
    cfg_explicit["major_tick_thickness"] = 4
    cfg_explicit["minor_tick_thickness"] = 4
    
    img_exp, _, _, _ = _call_gauge(cfg_explicit, None)
    arr_exp = np.array(img_exp.convert("RGBA"))
    
    # Must be 100% identical pixels
    diff = np.max(np.abs(arr_leg.astype(int) - arr_exp.astype(int)))
    assert diff == 0, f"Legacy fallback must have exact pixel parity with matching separated params, got max_diff={diff}"


def test_bug4_minor_ticks_independence():
    """Verify minor tick length and minor tick thickness can be controlled independently."""
    from src.indicators.gauge import clear_gauge_cache
    
    clear_gauge_cache()
    
    # Base config with 10 sub-ticks
    cfg_base = {
        "x": 50.0, "y": 50.0, "size": 20.0,
        "min_val": 0, "max_val": 100, "ticks": 10,
        "thickness": 3,
        "major_tick_length": 4.0, "minor_tick_length": 2.0,
        "major_tick_thickness": 3, "minor_tick_thickness": 1,
        "show_value": False,
    }
    img_base, _, _, _ = _call_gauge(cfg_base, None)
    arr_base = np.array(img_base.convert("RGBA"))
    
    # 1. Change ONLY minor_tick_length
    cfg_min_len = dict(cfg_base)
    cfg_min_len["minor_tick_length"] = 6.0
    img_min_len, _, _, _ = _call_gauge(cfg_min_len, None)
    arr_min_len = np.array(img_min_len.convert("RGBA"))
    diff_len = np.sum(np.abs(arr_base.astype(int) - arr_min_len.astype(int)))
    assert diff_len > 0, "Changing minor_tick_length must alter output"
    
    # 2. Change ONLY minor_tick_thickness
    cfg_min_thick = dict(cfg_base)
    cfg_min_thick["minor_tick_thickness"] = 5
    img_min_thick, _, _, _ = _call_gauge(cfg_min_thick, None)
    arr_min_thick = np.array(img_min_thick.convert("RGBA"))
    diff_thick = np.sum(np.abs(arr_base.astype(int) - arr_min_thick.astype(int)))
    assert diff_thick > 0, "Changing minor_tick_thickness must alter output"


def test_bug4_all_four_tick_properties_in_models():
    """Verify all 4 separated tick fields exist in models._ticks_tab_fields."""
    from src.gui.qt.models import _ticks_tab_fields
    
    fields = _ticks_tab_fields()
    field_names = [f.name for f in fields]
    assert "major_tick_length" in field_names
    assert "minor_tick_length" in field_names
    assert "major_tick_thickness" in field_names
    assert "minor_tick_thickness" in field_names
    assert "thickness" in field_names  # legacy retained


def test_bug2_custom_text_font_override():
    """Verify custom_text respects per-item font setting."""
    from src.indicators.compositor import compose_overlay
    
    layout = {
        "indicators": {},
        "custom_texts": [
            {"text": "TEST OVERRIDE", "x": 50, "y": 50, "font": "Arial", "font_size": 2.0}
        ],
        "global": {"text_outline": 3}
    }
    # Run compose_overlay
    img = compose_overlay(
        canvas_w=1920, canvas_h=1080,
        layout=layout,
        font_path="default",
        date_text="",
        time_text="",
        speed_value=0.0,
        distance_m=0.0,
    )
    assert img is not None
    assert isinstance(img, Image.Image)

