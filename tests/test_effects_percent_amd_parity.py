"""Tests for 0-100% effect parameters, legacy migration, resolution scaling, and compass parity."""
import math
import numpy as np
import pytest
from PIL import Image, ImageDraw

from src.gui.qt.models import _effects_fields, get_schema_for_form
from src.indicators.effects import (
    apply_indicator_effects,
    effects_enabled,
    is_effects_v2,
    migrate_indicator_effects,
    clear_effects_cache,
)


@pytest.fixture(autouse=True)
def clean_cache():
    clear_effects_cache()
    yield
    clear_effects_cache()


def sample_circle_image(size: int = 100) -> Image.Image:
    im = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    pad = int(size * 0.1)
    d.ellipse((pad, pad, size - pad, size - pad), fill=(255, 200, 0, 255))
    return im


def test_effects_schema_uses_percent_scale():
    """Etap 3: Schema fields must have 0-100 min/max, step 0.1 or 1, and [%] labels."""
    fields = {f.name: f for f in _effects_fields()}

    for name in ("outline_opacity", "outline_fade", "shadow_opacity", "shadow_fade"):
        f = fields[name]
        assert f.min_val == 0.0
        assert f.max_val == 100.0
        assert f.step == 1.0
        assert "[%]" in f.label

    for name in ("outline_width", "shadow_distance", "shadow_length"):
        f = fields[name]
        assert f.min_val == 0.0
        assert f.max_val == 100.0
        assert f.step == 0.1
        assert "[%]" in f.label

    assert fields["shadow_angle"].min_val == 0.0
    assert fields["shadow_angle"].max_val == 360.0
    assert fields["shadow_angle"].step == 5.0
    assert "[stopnie]" in fields["shadow_angle"].label


def test_fast_path_when_effects_disabled():
    """Etap 2: When effects are disabled, return original image instance with zero allocation."""
    im = sample_circle_image(100)
    assert apply_indicator_effects(im, {}, 540) is im
    assert apply_indicator_effects(im, {"outline_enabled": False, "shadow_enabled": False}, 540) is im
    assert apply_indicator_effects(im, {"outline_enabled": True, "outline_width": 0.0}, 540) is im


def test_effect_cache_distinguishes_rgb_and_mutated_source_rasters():
    """Cached effects must preserve current RGB pixels even when alpha is unchanged."""
    cfg = {
        "effects_version": 2,
        "outline_enabled": True,
        "outline_width": 10.0,
        "outline_opacity": 100.0,
        "outline_fade": 0.0,
    }

    red = Image.new("RGBA", (32, 32), (0, 0, 0, 0))
    ImageDraw.Draw(red).rectangle((8, 8, 23, 23), fill=(255, 0, 0, 255))
    green = Image.new("RGBA", (32, 32), (0, 0, 0, 0))
    ImageDraw.Draw(green).rectangle((8, 8, 23, 23), fill=(0, 255, 0, 255))

    red_result = apply_indicator_effects(red, cfg, 32)
    green_result = apply_indicator_effects(green, cfg, 32)
    center = (red_result.width // 2, red_result.height // 2)
    assert red_result.getpixel(center) == (255, 0, 0, 255)
    assert green_result.getpixel(center) == (0, 255, 0, 255)

    # The same PIL object may be reused and edited by a renderer between frames.
    red.paste((0, 0, 255, 255), (8, 8, 24, 24))
    blue_result = apply_indicator_effects(red, cfg, 32)
    assert blue_result.getpixel(center) == (0, 0, 255, 255)


def test_resolution_proportional_scaling_v2():
    """Etap 4: Geometric percentages scale relative to indicator min dimension."""
    im_540 = sample_circle_image(100)
    im_1080 = sample_circle_image(200)
    im_4k = sample_circle_image(400)

    cfg = {
        "effects_version": 2,
        "outline_enabled": True,
        "outline_width": 5.0,  # 5% of ref_dim
        "outline_opacity": 100.0,
        "outline_fade": 0.0,
    }

    res_540 = apply_indicator_effects(im_540, cfg, 540)
    res_1080 = apply_indicator_effects(im_1080, cfg, 1080)
    res_4k = apply_indicator_effects(im_4k, cfg, 2160)

    # 5% of 100 = 5 px; 5% of 200 = 10 px; 5% of 400 = 20 px
    pad_540 = (res_540.width - im_540.width) // 2
    pad_1080 = (res_1080.width - im_1080.width) // 2
    pad_4k = (res_4k.width - im_4k.width) // 2

    # Padding is max(width, dist) + 2
    assert pad_540 == 5 + 2
    assert pad_1080 == 10 + 2
    assert pad_4k == 20 + 2


def test_legacy_backward_compatibility_v1():
    """Etap 5: Layouts without effects_version: 2 are rendered with legacy 540p logical px formula."""
    im = sample_circle_image(100)
    cfg_legacy = {
        "outline_enabled": True,
        "outline_width": 2.0,  # 2 px at 540p
        "outline_opacity": 0.8,
        "outline_fade": 0.0,
        "shadow_enabled": True,
        "shadow_distance": 3.0,
        "shadow_length": 0.0,
        "shadow_opacity": 0.7,
        "shadow_fade": 1.0,
    }
    assert not is_effects_v2(cfg_legacy)

    # At 540p, scale = 1.0 -> width = 2, distance = 3
    res_540 = apply_indicator_effects(im, cfg_legacy, 540)
    pad_540 = (res_540.width - im.width) // 2
    assert pad_540 == 3 + 2

    # At 2160p (4K), scale = 4.0 -> width = 8, distance = 12
    res_4k = apply_indicator_effects(im, cfg_legacy, 2160)
    pad_4k = (res_4k.width - im.width) // 2
    assert pad_4k == 12 + 2


def test_migrate_indicator_effects_v1_to_v2():
    """Etap 5: Migration correctly converts legacy fractions and px to 0-100%."""
    cfg = {
        "outline_enabled": True,
        "outline_width": 2.0,
        "outline_opacity": 0.8,
        "outline_fade": 0.0,
        "shadow_enabled": True,
        "shadow_distance": 3.0,
        "shadow_length": 5.0,
        "shadow_opacity": 0.7,
        "shadow_fade": 0.5,
        "shadow_angle": 45.0,
    }
    migrated = migrate_indicator_effects(cfg, nominal_dim=100.0)

    assert migrated["effects_version"] == 2
    assert migrated["outline_opacity"] == 80.0
    assert migrated["outline_fade"] == 0.0
    assert migrated["shadow_opacity"] == 70.0
    assert migrated["shadow_fade"] == 50.0
    assert migrated["outline_width"] == 2.0
    assert migrated["shadow_distance"] == 3.0
    assert migrated["shadow_length"] == 5.0
    assert is_effects_v2(migrated)


def test_compass_both_rotation_modes_render_cleanly():
    """Etap 6: Compass renders cleanly in both needle and rose modes with effects on."""
    from src.indicators.gauge import _render_compass_indicator
    from src.indicators.effects import apply_indicator_effects

    cfg_needle = {
        "enabled": True,
        "form": "gauge",
        "gauge_style": "compass",
        "compass_rotation_mode": "needle",
        "x": 50.0,
        "y": 50.0,
        "size": 10.0,
        "outline_enabled": True,
        "outline_width": 2.0,
        "shadow_enabled": True,
        "shadow_distance": 3.0,
        "effects_version": 2,
    }
    res_needle, nx, ny, _ = _render_compass_indicator(
        canvas_w=1920, canvas_h=1080, layout={"indicators": {"compass": cfg_needle}},
        font_path=r"C:\Windows\Fonts\arial.ttf", key="compass", value=45.0,
        unit="°", label="COMPASS", cfg=cfg_needle, min_dim=1080, outline=3,
        fs=16, font=None, val_min=0, val_max=100, ticks=0, thickness=3,
        size_px=108, ss=1,
    )
    styled_needle = apply_indicator_effects(res_needle, cfg_needle, 1080)
    assert styled_needle is not None
    assert styled_needle.width > res_needle.width

    cfg_rose = dict(cfg_needle, compass_rotation_mode="rose")
    res_rose, rx, ry, _ = _render_compass_indicator(
        canvas_w=1920, canvas_h=1080, layout={"indicators": {"compass": cfg_rose}},
        font_path=r"C:\Windows\Fonts\arial.ttf", key="compass", value=45.0,
        unit="°", label="COMPASS", cfg=cfg_rose, min_dim=1080, outline=3,
        fs=16, font=None, val_min=0, val_max=100, ticks=0, thickness=3,
        size_px=108, ss=1,
    )
    styled_rose = apply_indicator_effects(res_rose, cfg_rose, 1080)
    assert styled_rose is not None
    assert styled_rose.width > res_rose.width
