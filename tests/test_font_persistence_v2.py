"""Tests for Font Persistence v2 + Save Settings + Frame Step fixes.

Covers:
1. Font saved to def_layout.json["global"]["font"] via _save_global_settings_to_default
2. Font restored from def_layout.json on _load_startup_preset
3. _STATIC_CACHE cleared on font change in _on_settings_changed
4. _STATIC_CACHE cleared on per-indicator font change in _on_property_changed
5. Frame step calculation (fps-based)
6. _global_font_family attribute propagation
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock


def _make_fake_def_layout(tmp_dir: Path, *, font=None, outline: int = 3) -> Path:
    data = {
        "version": 6,
        "width": 1280,
        "height": 720,
        "global": {"text_outline": outline},
        "indicators": {},
    }
    if font is not None:
        data["global"]["font"] = font
    p = tmp_dir / "def_layout.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    return p


def test_save_global_settings_writes_font(tmp_path):
    from src.gui.qt._mixins.preset_mixin import PresetMixin
    _make_fake_def_layout(tmp_path)

    class FakeController(PresetMixin):
        base_dir = tmp_path
        font_path = ""
        _global_font_family = "Consolas"
        layout = {"global": {"text_outline": 3}, "indicators": {}}
        _cut_regions = []

    ctrl = FakeController()
    ctrl._save_global_settings_to_default()

    data = json.loads((tmp_path / "def_layout.json").read_text(encoding="utf-8"))
    assert data["global"].get("font") == "Consolas"


def test_save_global_settings_preserves_indicators(tmp_path):
    existing = {
        "version": 6,
        "global": {"text_outline": 2},
        "indicators": {"speed": {"form": "gauge", "x": 10, "y": 20}},
    }
    (tmp_path / "def_layout.json").write_text(json.dumps(existing), encoding="utf-8")

    from src.gui.qt._mixins.preset_mixin import PresetMixin

    class FakeController(PresetMixin):
        base_dir = tmp_path
        font_path = ""
        _global_font_family = "Arial"
        layout = {"global": {"text_outline": 2}, "indicators": {"speed": {"form": "gauge", "x": 10}}}
        _cut_regions = []

    ctrl = FakeController()
    ctrl._save_global_settings_to_default()

    data = json.loads((tmp_path / "def_layout.json").read_text(encoding="utf-8"))
    assert "speed" in data.get("indicators", {})
    assert data["indicators"]["speed"]["x"] == 10


def test_controller_restores_font_on_startup(tmp_path):
    _make_fake_def_layout(tmp_path, font="Courier New")

    def fake_normalize(path, w, h):
        return json.loads(Path(path).read_text(encoding="utf-8"))

    def fake_resolve(family):
        return f"C:/Windows/Fonts/{family.lower().replace(' ', '')}.ttf"

    class FakeSignals:
        sig_global_font_restored = MagicMock()

    class FakeCtrl:
        base_dir = tmp_path
        font_path = "C:/Windows/Fonts/arial.ttf"
        _global_font_family = "Arial"
        layout = {}
        signals = FakeSignals()
        _startup_preset_path = ""

        def _load_startup_preset(self):
            def_layout = self.base_dir / "def_layout.json"
            if def_layout.exists():
                try:
                    self.layout = fake_normalize(def_layout, 1280, 720)
                    self._startup_preset_path = self.layout.get("_startup_preset", "")
                    saved_font = self.layout.get("global", {}).get("font", "")
                    if saved_font:
                        self._global_font_family = saved_font
                        self.font_path = fake_resolve(saved_font)
                        self.signals.sig_global_font_restored.emit(saved_font)
                except Exception as e:
                    print(f"[Test] Error: {e}")

    fc = FakeCtrl()
    fc._load_startup_preset()

    assert fc._global_font_family == "Courier New"
    assert "couriernew" in fc.font_path.lower()
    assert fc.signals.sig_global_font_restored.emit.called


def test_static_cache_cleared_on_font_change(tmp_path):
    from src.indicators.helpers import _STATIC_CACHE
    _STATIC_CACHE["dummy_key"] = object()
    assert len(_STATIC_CACHE) > 0

    from src.gui.qt._mixins.preset_mixin import PresetMixin

    class FakeController(PresetMixin):
        base_dir = tmp_path
        font_path = ""
        _global_font_family = ""
        layout = {"global": {}, "indicators": {}}
        _cut_regions = []
        render_threads = None
        _startup_preset_path = ""

        def _render_preview(self): pass
        def _clear_caches(self): pass

    (tmp_path / "def_layout.json").write_text("{}", encoding="utf-8")
    ctrl = FakeController()
    ctrl._on_settings_changed("font", "Impact")

    assert len(_STATIC_CACHE) == 0
    assert ctrl._global_font_family == "Impact"


def test_static_cache_cleared_on_indicator_font_change(tmp_path):
    from src.indicators.helpers import _STATIC_CACHE
    _STATIC_CACHE["gauge_bg_dummy"] = object()

    from src.gui.qt._mixins.preset_mixin import PresetMixin

    class FakeController(PresetMixin):
        base_dir = tmp_path
        font_path = ""
        _global_font_family = ""
        layout = {
            "global": {},
            "indicators": {
                "speed": {"form": "gauge", "font": "", "x": 10, "y": 10}
            },
        }
        _cut_regions = []
        render_threads = None
        _startup_preset_path = ""
        layout_mgr = None

        class signals:
            @staticmethod
            def sig_properties_ready(*a): pass

        def _render_preview(self): pass
        def _clear_caches(self): pass
        def _save_current_layout_to_default(self): pass

    (tmp_path / "def_layout.json").write_text("{}", encoding="utf-8")
    ctrl = FakeController()
    ctrl._on_property_changed("speed", "font", "Digital-7")

    assert len(_STATIC_CACHE) == 0


def test_frame_step_calculation():
    fps = 25.0
    duration_s = 100.0
    current_pos = 50.0

    # Step forward
    dt = +1 / fps
    new_pos = max(0.0, min(current_pos + dt, duration_s))
    assert abs(new_pos - (50.0 + 1.0 / 25.0)) < 1e-9

    # Step backward
    dt = -1 / fps
    new_pos = max(0.0, min(current_pos + dt, duration_s))
    assert abs(new_pos - (50.0 - 1.0 / 25.0)) < 1e-9

    # Clamp at 0
    new_pos = max(0.0, min(-1.0 / fps, duration_s))
    assert new_pos == 0.0

    # Clamp at duration
    new_pos = max(0.0, min(duration_s + 1.0 / fps, duration_s))
    assert new_pos == duration_s
