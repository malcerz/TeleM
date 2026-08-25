from copy import deepcopy

from src.gui.qt.models import _sync_size_font_fields, get_schema_for_form
from src.indicators.dispatcher import render_value_indicator
from src.indicators.helpers import _STATIC_CACHE


FONT = r"C:\Windows\Fonts\arial.ttf"


def _render(cfg):
    _STATIC_CACHE.clear()
    layout = {"global": {"text_outline": 3}, "indicators": {"temp_text": cfg}}
    image, x, y, _ = render_value_indicator(
        960, 540, layout, FONT, "temp_text", 30.4, "°C", "TGP",
        cfg_override=cfg, formatted_val="30.4 °C",
    )
    return image.size, (x, y)


def test_text_schema_has_one_canonical_size_control():
    schema = get_schema_for_form("text")
    names = [field.name for field in schema]
    assert names.count("font_size") == 1
    assert "size" not in names
    size_field = next(field for field in schema if field.name == "font_size")
    assert size_field.label == "Rozmiar"
    assert (size_field.min_val, size_field.max_val, size_field.step) == (0.5, 10.0, 0.1)


def test_legacy_size_event_does_not_jump_font_size():
    cfg = {
        "form": "text", "size": 10.0, "font_size": 2.5,
        "x": 1.65, "y": 49.48,
    }
    before = _render(cfg)
    cfg["size"] = 10.1  # compatibility with the old event path
    _sync_size_font_fields(cfg, "size")
    after = _render(cfg)
    assert cfg["font_size"] == 2.5
    assert before == after


def test_canonical_font_size_edit_updates_legacy_copy_once():
    cfg = {
        "form": "text", "size": 10.0, "font_size": 2.5,
        "x": 1.65, "y": 49.48,
    }
    cfg["font_size"] = 2.6
    _sync_size_font_fields(cfg, "font_size")
    assert cfg["font_size"] == cfg["size"] == 2.6
    assert _render(cfg)[0][0] < _render({**cfg, "font_size": 10.1, "size": 10.1})[0][0]


def test_text_font_size_only_and_legacy_size_only_fallbacks():
    font_only = {"form": "text", "font_size": 2.5, "x": 50.0, "y": 50.0}
    size_only = {"form": "text", "size": 2.5, "x": 50.0, "y": 50.0}
    assert _render(font_only)[0] == _render(size_only)[0]


def test_equal_text_fields_remain_unchanged():
    cfg = {"form": "text", "size": 2.5, "font_size": 2.5, "x": 50.0, "y": 50.0}
    before = deepcopy(cfg)
    _sync_size_font_fields(cfg, "font_size")
    assert cfg == before
