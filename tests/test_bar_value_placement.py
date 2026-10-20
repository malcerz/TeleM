from copy import deepcopy

import numpy as np
import pytest

from src.indicators import bar
from src.gui.qt.models import bar_indicator_fields
from tests.test_bar_orientation_contract import _cfg, _render


@pytest.mark.parametrize("orientation", ["horizontal", "vertical"])
@pytest.mark.parametrize("style", ["ruler", "segments"])
def test_default_preserves_existing_render_and_font_control(orientation, style):
    cfg = _cfg(orientation=orientation, bar_style=style, unit="°C")
    before = _render(cfg, 10.5)
    assert np.array_equal(before, _render(dict(cfg, value_position="moving"), 10.5))
    assert not np.array_equal(before, _render(dict(cfg, value_font_scale=2.0, value_font_size=2.0), 10.5))


@pytest.mark.parametrize("orientation", ["horizontal", "vertical"])
@pytest.mark.parametrize("style", ["ruler", "segments"])
@pytest.mark.parametrize("position", ["top", "bottom"])
@pytest.mark.parametrize("unit", ["C", "°C"])
def test_static_readout_band_is_bounded_separate_and_keeps_unit(monkeypatch, orientation, style, position, unit):
    bar.clear_bar_cache()
    cfg = _cfg(orientation=orientation, bar_style=style, value_position=position,
               unit=unit, min_val=-20, max_val=40, value_font_scale=2.0, value_font_size=2.0)
    original = deepcopy(cfg)
    # Populate the moving cache first: switching UI modes must not retain a
    # moving readout from the former vertical-ruler static base.
    _render(dict(cfg, value_position="moving"), 10.5)
    calls = []
    draw = bar.draw_text_with_graphic_degree
    def capture(*args, **kwargs):
        result = draw(*args, **kwargs)
        calls.append((args[2], result, kwargs["font"].size))
        return result
    monkeypatch.setattr(bar, "draw_text_with_graphic_degree", capture)
    image = _render(cfg, 10.5)
    text, box, font_size = calls[-1]
    assert text == f"10.5 {unit}"
    assert font_size > 10
    assert 0 <= box[0] < box[2] <= image.width
    assert 0 <= box[1] < box[3] <= image.height
    core = _render(dict(cfg, show_value=False), 10.5)
    band = image.height - core.height
    assert band > 0
    if position == "top":
        assert box[3] <= band
        region = image.crop(((image.width-core.width)//2, band, (image.width+core.width)//2, image.height))
    else:
        assert box[1] >= core.height
        region = image.crop(((image.width-core.width)//2, 0, (image.width+core.width)//2, core.height))
    assert np.array_equal(region, core)
    assert cfg == original


@pytest.mark.parametrize("position", ["top", "bottom"])
def test_static_position_independent_of_marker_and_font_size(monkeypatch, position):
    bar.clear_bar_cache()
    cfg = _cfg(orientation="vertical", value_position=position, unit="°C", min_val=-20, max_val=40)
    boxes = []
    draw = bar.draw_text_with_graphic_degree
    def capture(*args, **kwargs):
        box = draw(*args, **kwargs)
        if args[2] == "10.5 °C":
            boxes.append(box)
        return box
    monkeypatch.setattr(bar, "draw_text_with_graphic_degree", capture)
    for value in (-10, 30):
        _render(cfg, value, formatted="10.5 °C")
    assert boxes[-1] == boxes[-2]
    small = _render(cfg, 10.5)
    large = _render(dict(cfg, value_font_scale=3), 10.5)
    assert large.height > small.height


def test_schema_and_segment_unit_contract(monkeypatch):
    for style in ("ruler", "segments", "slope"):
        fields = {f.name: f for f in bar_indicator_fields(style)}
        assert [x[0] for x in fields["value_position"].choices] == ["moving", "top", "bottom"]
        assert ("value_font_size" if style == "segments" else "value_font_scale") in fields
    seen = []
    draw = bar.draw_text_with_graphic_degree
    def capture(*args, **kwargs):
        seen.append(args[2])
        return draw(*args, **kwargs)
    monkeypatch.setattr(bar, "draw_text_with_graphic_degree", capture)
    cfg = _cfg(bar_style="segments", value_position="top", unit="°C", value_show_unit=False)
    _render(cfg, 10.5)
    assert seen[-1] == "10.5"
    _render(dict(cfg, value_show_unit=True, value_unit="K"), 10.5)
    assert seen[-1] == "10.5 K"


def test_graphic_degree_bounded_text_accounts_for_draw_position(monkeypatch):
    from PIL import Image, ImageDraw
    image = Image.new("RGBA", (160, 50))
    captured = []
    draw = bar.draw_text_with_graphic_degree
    def capture(*args, **kwargs):
        box = draw(*args, **kwargs)
        captured.append(box)
        return box
    monkeypatch.setattr(bar, "draw_text_with_graphic_degree", capture)
    bar._draw_text_bounded(
        ImageDraw.Draw(image), (159, 49), "10.5 °C", font=bar.load_font("", 24),
        fill="white", stroke_width=1, stroke_fill="black", bounds=image.size, anchor="la",
    )
    left, top, right, bottom = captured[0]
    assert 0 <= left < right <= image.width
    assert 0 <= top < bottom <= image.height


def test_hidden_value_stays_hidden_in_all_positions():
    cfg = _cfg(orientation="vertical", show_value=False, unit="°C")
    moving = _render(cfg, 10.5)
    for position in ("top", "bottom"):
        assert np.array_equal(moving, _render(dict(cfg, value_position=position), 10.5))


@pytest.mark.parametrize("orientation", ["horizontal", "vertical"])
@pytest.mark.parametrize("position", ["moving", "top", "bottom"])
def test_temperature_preview_final_pixel_parity(orientation, position):
    from src.indicators.compositor import compose_overlay
    from src.telemetry_resolver import resolve_current_presentation
    from tests.test_amd_final_temperature_parity import _build, _frame_dt, FIT_TEMP

    cfg = _cfg(orientation=orientation, value_position=position, unit="°C",
               min_val=-20, max_val=40, source="fit", field="temperature")
    layout = {"indicators": {"fit_temperature_text": cfg}}
    cache = _build(layout)
    for width, height in ((960, 540), (1920, 1080), (3840, 2160)):
        for i in (15, 315):
            frame = cache.lookup(i)
            preview = resolve_current_presentation(FIT_TEMP, _frame_dt(i), "temperature", cfg)
            assert frame["extra_indicators"]["fit_temperature_text"][0] == pytest.approx(preview)
            final = compose_overlay(width, height, layout, "", **frame, reuse_canvas=False)
            frame["extra_indicators"] = {"fit_temperature_text": (preview, "°C", "TEST")}
            reference = compose_overlay(width, height, layout, "", **frame, reuse_canvas=False)
            assert np.array_equal(final, reference)  # max_diff=MAE=different_pixels=0
