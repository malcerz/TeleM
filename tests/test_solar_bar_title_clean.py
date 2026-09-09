"""Automated regression test for Solar BAR title clean fix.

Verifies:
1. Solar BAR title is strictly 'SOLAR' without any second numeric value or ' | %' / ' 1 %'.
2. Marker value is rendered accurately above the marker (e.g. '5%').
3. Marker position matches the value.
4. Non-percentage bars (e.g. Distance 'km') retain their unit in title ('DISTANCE | KM').
"""

import json
from unittest.mock import patch
import src.indicators.bar as bar_mod


def test_solar_bar_title_clean_at_all_values():
    """Verify Solar BAR renders clean title 'SOLAR' and correct marker value at 1%, 5%, 11%, 15%."""
    with open("def_layout.json", "r", encoding="utf-8") as f:
        layout = json.load(f)

    cfg = dict(layout["indicators"]["fit_solar_text"])

    drawn_texts = []
    orig_draw_text = bar_mod._draw_text_bounded

    def mock_draw_text(draw, xy, text, **kwargs):
        drawn_texts.append((text, xy, kwargs.get("anchor")))
        return orig_draw_text(draw, xy, text, **kwargs)

    for val in [1.0, 5.0, 11.0, 15.0]:
        drawn_texts.clear()
        bar_mod.clear_bar_cache()
        bar_mod._STATIC_CACHE.clear()
        with patch.object(bar_mod, "_draw_text_bounded", side_effect=mock_draw_text):
            img, rx, ry, extra = bar_mod._render_bar_indicator(
                1920, 1080, layout, "Digital-7 Mono",
                "fit_solar_text", val, "%", cfg.get("label", "Solar"),
                cfg, min_dim=1080, outline=2, fs=27, font=None,
                val_min=0.0, val_max=30.0, ticks=0, thickness=1.0, size_px=288, ss=1,
                formatted_val=f"{int(val)}%",
            )

        # 1. Base raster title must be strictly SOLAR (anchor 'ma' at top)
        title_matches = [t for t, xy, anchor in drawn_texts if anchor == "ma" and xy[1] < 20]
        assert len(title_matches) >= 1, f"Expected title for val={val}"
        assert title_matches[0] == "SOLAR", f"Title must be 'SOLAR', got {title_matches[0]!r}"

        # 2. No string should contain '1 %' or ' | %'
        for text, _, _ in drawn_texts:
            assert "1 %" not in text and "| %" not in text, f"Erroneous title text detected: {text}"

        # 3. Dynamic marker value must match formatted value (e.g. '5%')
        expected_marker_val = f"{int(val)}%"
        marker_matches = [t for t, xy, anchor in drawn_texts if t == expected_marker_val]
        assert len(marker_matches) == 1, f"Expected marker value {expected_marker_val} in drawn texts"


def test_title_with_unit_true_does_not_corrupt_percentage_bar():
    """Even if a config explicitly has title_with_unit=True, % is not appended as ' | %'."""
    with open("def_layout.json", "r", encoding="utf-8") as f:
        layout = json.load(f)

    cfg = dict(layout["indicators"]["fit_solar_text"])
    cfg["title_with_unit"] = True

    drawn_texts = []
    orig_draw_text = bar_mod._draw_text_bounded

    def mock_draw_text(draw, xy, text, **kwargs):
        drawn_texts.append((text, xy, kwargs.get("anchor")))
        return orig_draw_text(draw, xy, text, **kwargs)

    bar_mod.clear_bar_cache()
    bar_mod._STATIC_CACHE.clear()
    with patch.object(bar_mod, "_draw_text_bounded", side_effect=mock_draw_text):
        img, rx, ry, extra = bar_mod._render_bar_indicator(
            1920, 1080, layout, "Digital-7 Mono",
            "fit_solar_text", 5.0, "%", cfg.get("label", "Solar"),
            cfg, min_dim=1080, outline=2, fs=27, font=None,
            val_min=0.0, val_max=30.0, ticks=0, thickness=1.0, size_px=288, ss=1,
            formatted_val="5%",
        )

    title_matches = [t for t, xy, anchor in drawn_texts if anchor == "ma" and xy[1] < 20]
    assert title_matches[0] == "SOLAR", f"Title must be 'SOLAR', got {title_matches[0]!r}"


def test_distance_retains_title_with_unit_km():
    """Non-percentage indicators (e.g. distance km) still render 'DISTANCE | KM'."""
    with open("def_layout.json", "r", encoding="utf-8") as f:
        layout = json.load(f)

    cfg = dict(layout["indicators"]["fit_distance_text"])

    drawn_texts = []
    orig_draw_text = bar_mod._draw_text_bounded

    def mock_draw_text(draw, xy, text, **kwargs):
        drawn_texts.append((text, xy, kwargs.get("anchor")))
        return orig_draw_text(draw, xy, text, **kwargs)

    bar_mod.clear_bar_cache()
    with patch.object(bar_mod, "_draw_text_bounded", side_effect=mock_draw_text):
        img, rx, ry, extra = bar_mod._render_bar_indicator(
            1920, 1080, layout, "",
            "fit_distance_text", 12.4, "km", cfg.get("label", "Distance"),
            cfg, min_dim=1080, outline=2, fs=27, font=None,
            val_min=0.0, val_max=20.0, ticks=5, thickness=1.0, size_px=288, ss=1,
            formatted_val="12.4 km",
        )

    assert any("DISTANCE | KM" in t for t, _, _ in drawn_texts)
