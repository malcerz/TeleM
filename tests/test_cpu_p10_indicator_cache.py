"""P1.0: lean/compass cache changes must keep RGBA identical for any cache history."""
import random

from PIL import Image

from src.indicators import effects
from src.indicators.dispatcher import render_value_indicator
from src.indicators.gauge import _COMPASS_INDICATOR_CACHE, clear_compass_cache
from src.indicators.lean import _LEAN_ROTATED_PATCH_CACHE, clear_lean_caches

# Close angles around one 0.1° bucket plus the clamp limit (exact repeats).
ANGLES = [20.0, 20.001, 20.01, 20.04, 20.049, 20.05, 20.099, -0.3, 0.0, 31.0, 30.0, 45.0]

LAYOUT = {
    'global': {'text_outline': 1},
    'indicators': {
        'lean_indicator': {
            'x': 50, 'y': 50, 'size': 5, 'font_size': 2.5, 'form': 'lean', 'source': 'gyro',
            'graphic': 'bike', 'max_angle': 30, 'decimals': 1, 'show_value': True,
            'show_label': True, 'label': 'LEAN', 'show_reference': True, 'show_ticks': True,
            'effects_version': 2, 'shadow_enabled': True, 'outline_enabled': True,
            'outline_width': 3.0, 'outline_fade': 96.0, 'outline_opacity': 100.0,
        },
        'compass': {
            'x': 50, 'y': 50, 'form': 'gauge', 'gauge_style': 'compass', 'size': 7.8,
            'font_size': 2.8, 'compass_rotation_mode': 'rose', 'show_value': True, 'opacity': 0.9,
            'effects_version': 2, 'shadow_enabled': True, 'shadow_distance': 3.0, 'shadow_blur': 2.0,
        },
    },
}


def _render(key, value):
    fv = f'{value:.0f}' if key == 'compass' else None
    img, x, y, _ = render_value_indicator(3840, 2160, LAYOUT, 'arial.ttf', key, value, '°', 'X',
                                          formatted_val=fv, supersample=1)
    return img.size, x, y, img.tobytes()


def _clear():
    clear_lean_caches()
    clear_compass_cache()
    effects.clear_effects_cache()


def _fresh(key, value):
    _clear()
    return _render(key, value)


def test_close_angles_match_fresh_render_in_any_order():
    rng = random.Random(10)
    for key in ('lean_indicator', 'compass'):
        expected = {a: _fresh(key, a) for a in ANGLES}
        for _ in range(3):
            order = ANGLES * 2
            rng.shuffle(order)
            _clear()
            for a in order:
                assert _render(key, a) == expected[a], (key, a)


def test_lean_effects_uncached_path_matches_cached_path():
    cfg = LAYOUT['indicators']['lean_indicator']
    image = Image.new('RGBA', (120, 90), (0, 0, 0, 0))
    image.paste((250, 240, 10, 200), (20, 15, 70, 60))
    effects.clear_effects_cache()
    cached = effects.apply_indicator_effects(image, cfg, 2160)
    again = effects.apply_indicator_effects(image, cfg, 2160)  # cache hit
    image._effects_no_cache = True
    effects.clear_effects_cache()
    uncached = effects.apply_indicator_effects(image, cfg, 2160)
    assert len(effects._EFFECT_CACHE) == 0
    assert cached.tobytes() == again.tobytes() == uncached.tobytes()


def test_exact_angle_caches_stay_small():
    _clear()
    for i in range(50):
        _render('lean_indicator', 1.0 + i * 0.013)
        _render('compass', 100.0 + i * 0.013)
    assert len(_LEAN_ROTATED_PATCH_CACHE) <= _LEAN_ROTATED_PATCH_CACHE.max_entries == 8
    assert len(_COMPASS_INDICATOR_CACHE) <= _COMPASS_INDICATOR_CACHE.max_entries == 8
    # First-seen lean angles are not admitted to the shared effect cache.
    assert len(effects._EFFECT_CACHE) == 0
