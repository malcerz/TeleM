"""ETAP 5X-L: lean CPU layer (title/reference/ticks/value) used by AMD next to the GPU bike."""
import copy

from src.indicators import lean


def _cfg(**over):
    cfg = {
        "x": 50.0, "y": 50.0, "size": 5.0, "font_size": 2.5, "form": "lean", "source": "gyro",
        "title_text": "PRZECHYŁ", "show_label": True, "show_value": True,
        "show_reference": True, "show_ticks": True, "graphic": "bike", "max_angle": 30.0,
        "_skip_dynamic_graphic": True,
    }
    cfg.update(over)
    return cfg


def _render(cfg, value):
    layout = {"indicators": {"lean_indicator": cfg}}
    img, _, _, _ = lean._render_lean_indicator(
        3840, 2160, layout, "arial.ttf", "lean_indicator", value, "°", "PRZECHYŁ", cfg,
        2160, 2, 54, None, 0, 100, 0, 3, 400, 1,
    )
    return img


def test_static_layer_cached_and_bike_independent():
    lean.clear_lean_caches()
    a = _render(_cfg(), 5.0)
    n = len(lean._LEAN_BASE_CACHE)
    # A different angle reuses the static base (bike is GPU-owned here).
    b = _render(_cfg(), -3.0)
    assert len(lean._LEAN_BASE_CACHE) == n
    assert a.size == b.size


def test_setting_change_refreshes_and_restores():
    lean.clear_lean_caches()
    a = _render(_cfg(), 0.0)
    no_ticks = _render(_cfg(show_ticks=False), 0.0)
    assert a.tobytes() != no_ticks.tobytes()
    again = _render(_cfg(), 0.0)
    assert again.tobytes() == a.tobytes()


def test_empty_title_draws_no_title():
    lean.clear_lean_caches()
    with_title = _render(_cfg(), 0.0)
    no_title = _render(_cfg(title_text=""), 0.0)
    assert no_title.height < with_title.height or no_title.tobytes() != with_title.tobytes()
    cfg = _cfg(title_text="")
    cfg2 = copy.deepcopy(cfg)
    assert _render(cfg, 0.0).tobytes() == _render(cfg2, 0.0).tobytes()


def test_amd_exporter_restores_lean_availability_from_values():
    import inspect
    import src.ffmpeg.amd_native_exporter as amd
    src = inspect.getsource(amd.export_amd_native_d3d11)
    assert "lean availability from precomputed values" in src
    assert '"_indicator_availability" not in layout' in src
