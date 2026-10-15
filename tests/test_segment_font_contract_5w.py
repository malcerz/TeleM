"""5W: verify the already implemented independent Segments fonts."""
import copy
import json

import numpy as np
import pytest

from src.indicators.bar import _render_segments, clear_bar_cache

ARIAL = r"C:\Windows\Fonts\arial.ttf"
COURIER = r"C:\Windows\Fonts\cour.ttf"
TIMES = r"C:\Windows\Fonts\times.ttf"


def segment(cfg=None):
    settings = dict(segments=8, segment_gap=3, segment_height=25, show_value=True,
                    show_label=True, show_min=True, show_max=True, icon="none",
                    value_align="left", value_show_unit=False, decimals=0)
    settings.update(cfg or {})
    return _render_segments(canvas_w=1920, canvas_h=1080, font_path=ARIAL,
                            value=50, unit="%", label="POWER", cfg=settings,
                            val_min=0, val_max=100, size_px=500, fs=40,
                            outline=1, ss=1, formatted_val=None)


@pytest.mark.parametrize("field", ["value", "label", "range"])
def test_each_font_changes_pixels_independently_and_reuses_cache(field, monkeypatch):
    import src.indicators.bar as bar
    loaded = []
    original = bar.load_font
    def observe(path, size):
        loaded.append(path)
        return original(path, size)
    monkeypatch.setattr(bar, "load_font", observe)
    clear_bar_cache()
    baseline = segment()
    a = segment({f"{field}_font": COURIER})
    before = bar._SEG_BASE_CACHE.hits
    again = segment({f"{field}_font": COURIER})
    assert COURIER in loaded
    assert not np.array_equal(np.array(baseline), np.array(a))
    assert a is again
    assert bar._SEG_BASE_CACHE.hits > before
    assert np.array_equal(np.array(baseline), np.array(segment()))


def test_three_fonts_gui_persist_and_default_is_unchanged(tmp_path):
    from PySide6.QtWidgets import QApplication
    from src.gui.qt.models import get_schema_for_form
    from src.gui.qt.widgets.property_editor import PropertyEditor
    app = QApplication.instance() or QApplication([])
    cfg = {"form": "bar", "bar_style": "segments", "value_font": "", "label_font": "", "range_font": ""}
    original = segment()
    empty = segment(cfg)
    assert np.array_equal(np.array(original), np.array(empty))
    editor = PropertyEditor()
    editor.on_properties_ready("power_text", get_schema_for_form("bar", bar_style="segments"), copy.deepcopy(cfg))
    def receive(key, name, value):
        if key == "power_text":
            cfg[name] = value
    editor.signals.sig_property_changed.connect(receive)
    try:
        for key, font in [("value_font", COURIER), ("label_font", TIMES), ("range_font", ARIAL)]:
            editor._field_widgets[key].setText(font)
        app.processEvents()
        path = tmp_path / "layout.json"
        path.write_text(json.dumps(cfg), encoding="utf-8")
        saved = json.loads(path.read_text())
        assert saved["value_font"] == COURIER and saved["label_font"] == TIMES and saved["range_font"] == ARIAL
        changed = segment(saved)
        assert not np.array_equal(np.array(original), np.array(changed))
    finally:
        editor.signals.sig_property_changed.disconnect(receive)
        editor.close()
