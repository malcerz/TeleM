"""CPU HUD rendering must not depend on which nearby angle warmed a cache."""
from src.indicators.gauge import _render_compass_indicator, clear_compass_cache
from src.indicators.lean import _render_lean_indicator, clear_lean_caches


def test_compass_cache_is_independent_of_previous_angle():
    cfg = {'x': 50, 'y': 50, 'form': 'compass', 'size': 5,
           'compass_rotation_mode': 'rose', 'show_value': False}
    def render(value):
        return _render_compass_indicator(
            3840, 2160, {}, 'arial.ttf', 'compass', value, '°', 'COMPASS',
            cfg, 2160, 2, 28, None, 0, 360, 10, 4, 240, 2,
            formatted_val='020')[0].tobytes()
    clear_compass_cache()
    expected = render(20.04)
    clear_compass_cache()
    render(20.01)
    assert render(20.04) == expected


def test_lean_cache_is_independent_of_previous_angle():
    cfg = {'x': 50, 'y': 50, 'size': 5, 'font_size': 2.5, 'form': 'lean',
           'source': 'gyro', 'graphic': 'bike', 'max_angle': 30,
           'show_value': False, 'show_label': False,
           'show_reference': True, 'show_ticks': True}
    def render(value):
        return _render_lean_indicator(
            3840, 2160, {'indicators': {'lean_indicator': cfg}}, 'arial.ttf',
            'lean_indicator', value, '°', 'LEAN', cfg, 2160, 2, 54, None,
            0, 100, 0, 3, 400, 1)[0].tobytes()
    clear_lean_caches()
    expected = render(20.04)
    clear_lean_caches()
    render(20.01)
    assert render(20.04) == expected
