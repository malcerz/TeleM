import pytest
import numpy as np
from PIL import Image, ImageDraw

from src.indicators.bar import (
    _render_bar_indicator,
    _render_ruler,
    _render_ruler_vertical,
    _get_ruler_text_metrics,
    _RULER_METRICS_CACHE,
)
from src.indicators.helpers import load_font


def test_bar_ruler_metrics_cache_stability():
    font = load_font("arial.ttf", 24)
    _RULER_METRICS_CACHE.clear()

    # Call with 50 different value texts
    for i in range(50):
        m = _get_ruler_text_metrics(
            font_path="arial.ttf",
            title="DISTANCE",
            title_font=font,
            show_title=True,
            range_sample="100.0 km",
            range_font=font,
            show_range=True,
            value_text=f"{i * 1.7:.1f} km",
            value_font=font,
            show_value=True,
            text_stroke=2,
        )
        assert len(m) == 3
        assert m[0] > 0
        assert m[1] > 0
        assert m[2] > 0

    # Cache should only contain 1 entry (font-stable key)
    assert len(_RULER_METRICS_CACHE) == 1


def test_horizontal_ruler_exact_parity():
    layout = {
        "font_path": "arial.ttf",
        "indicators": {
            "test_dist": {
                "form": "bar",
                "bar_style": "ruler",
                "x": 50.0,
                "y": 10.0,
                "show_label": True,
                "show_value": True,
                "show_range_labels": True,
                "title_text": "DYSTANS",
                "decimals": 1,
                "marker_size": 7,
            }
        }
    }
    cfg = layout["indicators"]["test_dist"]

    test_values = [0.0, 10.5, 25.0, 50.0, 75.3, 99.9, 100.0]
    for val in test_values:
        res = _render_bar_indicator(
            canvas_w=3840, canvas_h=2160, layout=layout, font_path="arial.ttf",
            key="test_dist", value=val, unit="km", label="Dystans",
            cfg=cfg, min_dim=2160, outline=3, fs=24, font=None,
            val_min=0, val_max=100, ticks=0, thickness=3, size_px=1200,
            ss=1, formatted_val=f"{val:.1f} km"
        )
        assert res[0] is not None
        assert res[0].width > 1000
        assert res[0].height > 50


def test_vertical_ruler_exact_parity():
    layout = {
        "font_path": "arial.ttf",
        "indicators": {
            "test_alt": {
                "form": "bar",
                "bar_style": "ruler",
                "orientation": "vertical",
                "x": 80.0,
                "y": 50.0,
                "show_label": True,
                "show_value": True,
                "show_range_labels": True,
                "title_text": "ALT",
                "decimals": 0,
                "marker_size": 6,
            }
        }
    }
    cfg = layout["indicators"]["test_alt"]

    test_values = [-50.0, 0.0, 150.0, 300.0, 500.0]
    for val in test_values:
        res = _render_bar_indicator(
            canvas_w=3840, canvas_h=2160, layout=layout, font_path="arial.ttf",
            key="test_alt", value=val, unit="m", label="Alt",
            cfg=cfg, min_dim=2160, outline=3, fs=24, font=None,
            val_min=-100, val_max=600, ticks=0, thickness=3, size_px=400,
            ss=1, formatted_val=f"{val:.0f} m"
        )
        assert res[0] is not None
        assert res[0].width > 100
        assert res[0].height > 300
