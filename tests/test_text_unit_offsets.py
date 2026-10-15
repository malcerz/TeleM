"""5W: independent unit placement, legacy ink, GUI persistence and cache."""
import copy
import json
import subprocess
import types
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from src.indicators.text import _render_text_indicator, clear_text_cache, get_text_cache_stats

ROOT = Path(__file__).resolve().parents[1]
FONT = r"C:\Windows\Fonts\arial.ttf"


def render(cfg=None, *, width=1920, height=1080, fs=42, unit="km/h", renderer=_render_text_indicator):
    cfg = dict({"form": "text", "x": 10., "y": 20., "icon": "none", "text_color": "#FFFFFF"}, **(cfg or {}))
    return renderer(width, height, {}, FONT, "speed_text", 25.4, unit, "", cfg,
                    min(width, height), 1, fs, None, 0, 100, 0, 1, 100, 1,
                    formatted_val=f"25.4 {unit}".strip())


@pytest.fixture(scope="module")
def legacy_renderer():
    source = subprocess.check_output(["git", "show", "cbe0dd4:src/indicators/text.py"], cwd=ROOT, text=True)
    module = types.ModuleType("legacy_5w_text")
    exec(compile(source, "legacy_5w_text", "exec"), module.__dict__)
    return module._render_text_indicator


@pytest.mark.parametrize("fs", [18, 42, 84])
@pytest.mark.parametrize("unit", ["", "km/h", "°C"])
def test_zero_defaults_are_pixel_exact_with_legacy(fs, unit, legacy_renderer):
    old = render(fs=fs, unit=unit, renderer=legacy_renderer)
    new = render(dict(text_distance=0, unit_offset_x=0, unit_offset_y=0), fs=fs, unit=unit)
    assert old[1:3] == new[1:3]
    assert np.array_equal(np.array(old[0]), np.array(new[0]))


def paste(result, rotation):
    image, x, y, _ = result
    if rotation:
        image = image.rotate(rotation, expand=True)
    canvas = Image.new("RGBA", (1920, 1080))
    canvas.alpha_composite(image, (x, y))
    return np.array(canvas)


@pytest.mark.parametrize("rotation", [0, 90, 180, 270])
@pytest.mark.parametrize("settings", [dict(text_distance=30), dict(unit_offset_x=.03),
                                      dict(unit_offset_y=-.05), dict(unit_offset_x=-.2)])
def test_unit_moves_and_value_stays_anchored(rotation, settings):
    base = render(dict(rotation=rotation))
    changed = render(dict(rotation=rotation, **settings))
    a, b = paste(base, rotation), paste(changed, rotation)
    assert not np.array_equal(a, b)
    # The leading value half of the original tile cannot move when its unit moves.
    w, h = base[0].size
    region = Image.new("L", (w, h))
    from PIL import ImageDraw
    ImageDraw.Draw(region).rectangle((0, 0, int(w * .4), h - 1), fill=255)
    if rotation:
        region = region.rotate(rotation, expand=True)
    mask = Image.new("L", (1920, 1080))
    mask.paste(region, base[1:3])
    selected = np.array(mask) != 0
    assert np.array_equal(a[selected], b[selected])


def test_offsets_without_unit_are_ignored():
    a = render(unit="")
    b = render(dict(text_distance=50, unit_offset_x=-.05, unit_offset_y=.05), unit="")
    assert np.array_equal(np.array(a[0]), np.array(b[0])) and a[1:3] == b[1:3]


def test_graphic_degree_moves_with_unit_without_font_degree(monkeypatch):
    import src.indicators.helpers as helpers
    calls = []
    original = helpers.draw_graphic_degree_symbol
    def observe(*args, **kwargs):
        calls.append(args[1])
        return original(*args, **kwargs)
    monkeypatch.setattr(helpers, "draw_graphic_degree_symbol", observe)
    clear_text_cache()
    a = render(unit="°C")
    b = render(dict(unit_offset_y=.02), unit="°C")
    assert calls and not np.array_equal(np.array(a[0]), np.array(b[0]))


def test_text_cache_changes_only_with_relevant_state():
    clear_text_cache()
    a = render()
    moved = render(dict(unit_offset_x=.02))
    again = render()
    same = render(dict(unit_offset_x=.02))
    assert a[0] is again[0] and moved[0] is same[0]
    assert get_text_cache_stats()["hits"] == 2


def test_distance_scales_with_canvas_not_dpi():
    a = render(dict(text_distance=30), width=1920, height=1080, fs=42)
    b = render(dict(text_distance=30), width=3840, height=2160, fs=84)
    # Unit gap itself scales by two; no devicePixelRatio enters the renderer.
    a0 = render(width=1920, height=1080, fs=42)
    b0 = render(width=3840, height=2160, fs=84)
    assert a[0].width - a0[0].width == 30
    assert b[0].width - b0[0].width == 60


def test_gui_controls_emit_and_json_preserves_values(tmp_path):
    from PySide6.QtWidgets import QApplication
    from src.gui.qt.models import get_schema_for_form
    from src.gui.qt.widgets.property_editor import PropertyEditor
    app = QApplication.instance() or QApplication([])
    values = {"form": "text", "text_distance": 0., "unit_offset_x": 0., "unit_offset_y": 0.}
    editor = PropertyEditor()
    editor.on_properties_ready("speed_text", get_schema_for_form("text"), copy.deepcopy(values))
    def receive(key, field, value):
        if key == "speed_text":
            values[field] = value
    editor.signals.sig_property_changed.connect(receive)
    try:
        for name, val in [("text_distance", 24.), ("unit_offset_x", .03), ("unit_offset_y", -.02)]:
            editor._field_widgets[name].setValue(val)
        app.processEvents()
        path = tmp_path / "layout.json"
        path.write_text(json.dumps(values), encoding="utf-8")
        saved = json.loads(path.read_text())
        assert saved["text_distance"] == 24 and saved["unit_offset_x"] == .03 and saved["unit_offset_y"] == -.02
        assert not np.array_equal(np.array(render()[0]), np.array(render(saved)[0]))
    finally:
        editor.signals.sig_property_changed.disconnect(receive)
        editor.close()
