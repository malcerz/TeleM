"""ETAP 5D: final static chart assembly must remain raw-RGBA identical."""

from src.indicators.dispatcher import render_value_indicator


def _render(key, history, position, value="87"):
    cfg = {
        "enabled": True, "form": "chart", "x": 20.0, "y": 85.0,
        "size": 30.0, "font_size": 1.8, "min_val": 0, "max_val": 140,
        "label_count": 3, "show_grid": True, "show_average": True,
        "chart_color": "#FFAA11", "fill_color": "#771133",
        "fill_alpha": 157, "grid_color": "#345678", "line_width": 3,
        "text_color": "#DDEEFF", "text_offset_x": 0.01,
        "text_offset_y": -0.01,
    }
    layout = {"global": {"text_outline": 3}, "indicators": {key: cfg}}
    return render_value_indicator(
        640, 360, layout, "arial.ttf", key, 87.0, "rpm", "Cadence",
        cfg_override=cfg, formatted_val=value, history_data=history,
        current_position=position,
    )[0]


def test_final_static_assembly_matches_legacy_rgba_for_cursor_positions():
    history = [0.0, 140.0, 70.0, 70.0, 5.0, 139.0]
    for position in (0.0, 0.01, 0.25, 0.5, 0.99, 1.0):
        optimized = _render("fit_cadence_text", history, position)
        legacy = _render("fit_power_text", history, position)
        assert optimized.tobytes() == legacy.tobytes()


def test_final_static_cache_key_covers_history_and_dynamic_label():
    first = _render("fit_heart_rate_text", [70.0, 80.0, 90.0], 0.5, "80")
    changed = _render("fit_heart_rate_text", [90.0, 75.0, 110.0], 0.5, "75")
    first_legacy = _render("fit_power_text", [70.0, 80.0, 90.0], 0.5, "80")
    changed_legacy = _render("fit_power_text", [90.0, 75.0, 110.0], 0.5, "75")
    assert first.tobytes() == first_legacy.tobytes()
    assert changed.tobytes() == changed_legacy.tobytes()
    assert first.tobytes() != changed.tobytes()


def test_final_static_assembly_preserves_missing_cursor_and_label_semantics():
    history = [42.0, 42.0, 42.0]
    optimized = _render("fit_cadence_text", history, None, "--")
    legacy = _render("fit_power_text", history, None, "--")
    assert optimized.tobytes() == legacy.tobytes()
