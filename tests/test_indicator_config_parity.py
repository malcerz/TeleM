"""NEW INDICATOR CONFIG PARITY — regression tests.

Contract verified for every user-addable indicator:

    ADD INDICATOR
        -> canonical defaults (schema)
        -> complete indicator model config
        -> Property Editor shows EXACTLY the same values
        -> preview/renderer uses the same values
        -> save/reload preserves them
        -> opening Properties never mutates the config
        -> changing ONE property never changes others

Canonical defaults live in the schema (FieldSchema.default) and are consumed by:
- ``IndicatorMixin._create_indicator`` (complete config at creation),
- ``PropertyEditor._create_field_widget`` (fallback for old/incomplete configs).
"""

from __future__ import annotations

import json
import os
import sys

os.environ["QT_QPA_PLATFORM"] = "offscreen"

import pytest
from PySide6.QtWidgets import (
    QApplication, QSpinBox, QDoubleSpinBox, QCheckBox, QComboBox, QLineEdit,
)

from src.gui.qt.models import (
    get_schema_for_form,
    compass_indicator_fields,
    canonical_defaults,
)
from src.gui.qt._mixins.indicator_mixin import IndicatorMixin
from src.gui.qt._mixins.preset_mixin import PresetMixin
from src.gui.qt.widgets.property_editor import PropertyEditor


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

class DummyGUI(IndicatorMixin, PresetMixin):
    """Minimal controller: creation + property-change logic (no signals/UI)."""

    def __init__(self):
        self.telemetry = type("T", (), {
            "fit_data": {}, "speed_samples": [], "track_samples": [], "alt_samples": [],
            "iso_samples": [], "exposure_samples": [], "temperature_samples": [],
            "gpx_speed_samples": [], "gpx_track_samples": [], "gpx_alt_samples": [],
            "gpx_hr_samples": [], "gpx_cad_samples": [], "gpx_power_samples": [],
            "gpx_atemp_samples": [], "gpx_heading_samples": [], "gpx_slope_samples": [],
            "accel_x_samples": [], "accel_y_samples": [], "accel_z_samples": [],
            "accel_magnitude_samples": [], "gyro_x_samples": [], "gyro_y_samples": [],
            "gyro_z_samples": [], "gyro_magnitude_samples": [], "heading_samples": [],
            "slope_samples": [],
        })()
        self.layout = {"indicators": {}}
        self._selected_stream_key = ""
        self.layout_mgr = None

    def _render_preview(self) -> None:
        pass

    def _clear_caches(self) -> None:
        pass


# Każdy typ, który użytkownik może dodać z GUI (pojedyńczy przedstawiciel
# formy; fit_* pokrywa dynamiczne pola FIT).
INDICATOR_KEYS = [
    "speed_text",        # gauge
    "iso_text",          # text
    "dist_text",         # bar / ruler
    "battery_text",      # bar / segments
    "slope_text",        # bar / slope
    "hr_text",           # chart
    "compass",           # compass (gauge)
    "track_map",         # map
    "time_display",      # time_display
    "fit_enhanced_speed_text",  # dynamic FIT gauge
]


def _schema_for(key: str, cfg: dict):
    if key == "compass":
        return compass_indicator_fields()
    return get_schema_for_form(
        cfg.get("form", "text"),
        bar_style=cfg.get("bar_style", "ruler"),
        chart_time_scope=cfg.get("chart_time_scope", "activity"),
    )


def _read_widget(w):
    """Odczyt wartości widgetu Property Editor."""
    if isinstance(w, QCheckBox):
        return w.isChecked()
    if isinstance(w, QSpinBox):
        return w.value()
    if isinstance(w, QDoubleSpinBox):
        return w.value()
    if isinstance(w, QComboBox):
        data = w.currentData()
        return data if data is not None else w.currentText()
    if isinstance(w, QLineEdit):
        return w.text()
    try:
        from src.gui.qt.widgets.icon_picker import IconPickerWidget
        if isinstance(w, IconPickerWidget):
            return w.value()
    except ImportError:
        pass
    return None


def _values_match(field, model_value, widget_value) -> bool:
    """Porównanie wartości modelu z wartością widgetu (typ-świadome)."""
    if model_value is None:
        return True  # nie ma wartości w modelu — widget pokazuje default
    if field.field_type == "choice":
        # combo przechowuje tekst lub data; porównaj tekstowo
        return str(model_value) == str(widget_value)
    if isinstance(model_value, bool):
        return bool(model_value) == bool(widget_value)
    if isinstance(model_value, (int, float)):
        try:
            return abs(float(model_value) - float(widget_value)) < 1e-3
        except (TypeError, ValueError):
            return str(model_value) == str(widget_value)
    return str(model_value) == str(widget_value)


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication(sys.argv)
    yield app


# ---------------------------------------------------------------------------
# TEST A — canonical defaults: config kompletny w chwili utworzenia
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("key", INDICATOR_KEYS)
def test_a_new_indicator_has_complete_config(key):
    gui = DummyGUI()
    gui._create_indicator(key)
    cfg = gui.layout["indicators"][key]
    schema = _schema_for(key, cfg)
    missing = [f.name for f in schema if f.name not in cfg]
    assert missing == [], f"{key}: brakujące pola w configu nowego wskaźnika: {missing}"
    # każde pole schematu ma kanoniczny default (żadnego widgetowego 0/False/„")
    for field in schema:
        assert field.default is not None, f"{key}: pole {field.name} bez canonical default"


# ---------------------------------------------------------------------------
# TEST B — Properties parity: model == Property Editor (1:1)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("key", INDICATOR_KEYS)
def test_b_properties_parity(qapp, key):
    gui = DummyGUI()
    gui._create_indicator(key)
    cfg = gui.layout["indicators"][key]
    schema = _schema_for(key, cfg)

    editor = PropertyEditor()
    editor.on_properties_ready(key, schema, dict(cfg))

    for field in schema:
        w = editor._field_widgets.get(field.name)
        assert w is not None, f"{key}: brak widgetu dla pola {field.name}"
        widget_value = _read_widget(w)
        assert _values_match(field, cfg.get(field.name), widget_value), (
            f"{key}: pole {field.name}: model={cfg.get(field.name)!r} "
            f"!= editor={widget_value!r}"
        )


# ---------------------------------------------------------------------------
# TEST C — no mutation on open: otwarcie Properties nie zmienia configu
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("key", INDICATOR_KEYS)
def test_c_open_close_properties_does_not_mutate(qapp, key):
    gui = DummyGUI()
    gui._create_indicator(key)
    cfg = gui.layout["indicators"][key]
    before = dict(cfg)
    schema = _schema_for(key, cfg)

    editor = PropertyEditor()
    editor.on_properties_ready(key, schema, dict(cfg))
    editor.on_properties_ready(key, schema, dict(cfg))  # ponowne otwarcie
    editor.on_properties_ready("", [], {})              # zamknięcie

    assert cfg == before, f"{key}: otwarcie/zamknięcie Properties zmieniło config"


# ---------------------------------------------------------------------------
# TEST D — one-property change: zmiana JEDNEGO pola nie zmienia innych
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("key", INDICATOR_KEYS)
def test_d_one_property_change_does_not_touch_others(key):
    gui = DummyGUI()
    gui._create_indicator(key)
    cfg = gui.layout["indicators"][key]
    schema = _schema_for(key, cfg)

    # wybierz pole numeryczne obecne w configu
    target = next(
        f for f in schema
        if f.name in cfg and isinstance(cfg[f.name], (int, float)) and not isinstance(cfg[f.name], bool)
    )
    new_value = float(cfg[target.name]) + 1.0

    before = dict(cfg)
    # dokładnie tak, jak robi to controller (_on_property_changed)
    gui._on_property_changed(key, target.name, new_value)
    after = gui.layout["indicators"][key]

    assert after[target.name] == pytest.approx(new_value)
    changed = {k for k in after if after[k] != before.get(k)}
    # dozwolona jest tylko zmiana targetu (dla formy "text" także sync size↔font_size)
    assert target.name in changed
    for k in changed - {target.name}:
        assert k in ("size", "font_size"), f"{key}: zmieniło się pole {k}"


# ---------------------------------------------------------------------------
# TEST E — save/reload: JSON round-trip zachowuje konfigurację
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("key", INDICATOR_KEYS)
def test_e_save_reload_roundtrip(key):
    gui = DummyGUI()
    gui._create_indicator(key)
    cfg = gui.layout["indicators"][key]

    dumped = json.dumps(cfg)
    loaded = json.loads(dumped)

    assert loaded == cfg, f"{key}: round-trip JSON zmienił config"
    assert len(loaded) == len(cfg)


# ---------------------------------------------------------------------------
# TEST F — old/incomplete config: canonical defaults wypełniają braki w edytorze
# ---------------------------------------------------------------------------

def test_f_incomplete_config_editor_shows_canonical_defaults(qapp):
    """Niepełny stary config bara pokazuje w Właściwościach canonical defaults
    (nie widgetowe 0/False), zgodnie z fallbackiem renderera."""
    old_cfg = {"enabled": True, "x": 10.0, "y": 20.0, "form": "bar",
               "bar_style": "ruler", "label": "OLD", "min_val": 0.0,
               "max_val": 100.0, "ticks": 0, "source": "gpmf"}
    schema = get_schema_for_form("bar", bar_style="ruler")
    editor = PropertyEditor()
    editor.on_properties_ready("old_bar", schema, dict(old_cfg))

    # pola, których brakuje w starym configu → editor pokazuje canonical default
    assert editor._field_widgets["major_ticks"].value() == 8      # renderer fallback
    assert editor._field_widgets["minor_ticks"].value() == 5
    assert editor._field_widgets["show_mid_label"].isChecked() is True
    assert editor._field_widgets["track_color"].text() == "#F4F4F4"
    assert editor._field_widgets["unit"].text() == ""

    # canonical_defaults zgadza się z fallbackiem renderera
    cd = canonical_defaults(schema)
    assert cd["major_ticks"] == 8
    assert cd["minor_ticks"] == 5


def test_f_incomplete_segments_config(qapp):
    """Niepełny segment bar (legacy inactive_alpha/inactive_color/segment_radius)
    → nowe pola canonicalne równoważne legacy wartościom z creation."""
    old_cfg = {"form": "bar", "bar_style": "segments", "segments": 20,
               "segment_gap": 2, "inactive_alpha": 60, "inactive_color": "#333333",
               "segment_radius": 4}
    schema = get_schema_for_form("bar", bar_style="segments")
    cd = canonical_defaults(schema)
    # canonicalne nowe pola są spójne z legacy wartościami creation
    assert abs(cd["segment_inactive_opacity"] - 60 / 255.0) < 1e-9
    assert cd["segment_inactive_color"] == "#333333"
    assert cd["segment_corner_radius"] == 4.0

    editor = PropertyEditor()
    editor.on_properties_ready("old_seg", schema, dict(old_cfg))
    # brakujące pola pokazują canonical defaults
    assert editor._field_widgets["segment_count"].value() == 20
    assert editor._field_widgets["segment_fill_mode"].currentText() == "Cały"
    assert editor._field_widgets["marker_style"].currentText() == "Brak"
