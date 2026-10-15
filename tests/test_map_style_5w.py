"""Destination-space map styling: persisted names, AA, cache, and geometry."""
import numpy as np
import pytest
from PIL import Image

from src.indicators.helpers import apply_map_shape, map_style_layers, _map_style_layers


@pytest.mark.parametrize("shape", ["rectangle", "rounded", "round", "circle"])
@pytest.mark.parametrize("size", [(96, 64), (64, 96), (96, 96)])
def test_shape_border_and_source_ownership(shape, size):
    source = Image.new("RGBA", size, (20, 70, 130, 255))
    original = source.tobytes()
    result = apply_map_shape(source, shape, 18, 4, "#EF3010")
    assert source.tobytes() == original
    assert result.getpixel((size[0] // 2, size[1] // 2)) == (20, 70, 130, 255)
    # Top edge is AA-blended with the map for curved shapes; allow 1 LSB.
    edge = result.getpixel((size[0] // 2, 0))[:3]
    assert all(abs(a - b) <= 1 for a, b in zip(edge, (239, 48, 16)))
    assert result.getpixel((0, 0))[3] < 10 if shape != "rectangle" else result.getpixel((0, 0))[3] == 255
    if shape != "rectangle":
        assert np.any((np.array(result)[:, :, 3] > 0) & (np.array(result)[:, :, 3] < 255))


def test_radius_zero_clamp_border_zero_and_default_identity():
    image = Image.new("RGBA", (80, 60), (40, 90, 160, 255))
    assert apply_map_shape(image, "rectangle") is image
    assert apply_map_shape(image, "square") is image
    assert apply_map_shape(image, "rounded", 0).tobytes() == image.tobytes()
    assert apply_map_shape(image, "rounded", 1000).tobytes() == apply_map_shape(image, "rounded", 30).tobytes()
    assert apply_map_shape(image, "round").tobytes() == apply_map_shape(image, "circle").tobytes()
    assert apply_map_shape(image, "rounded", 10, 0, "#FF0000").tobytes() == apply_map_shape(image, "rounded", 10, 0, "#00FF00").tobytes()


def test_cached_style_dpi_scaling_color_and_no_source_alpha_resurrection():
    _map_style_layers.cache_clear()
    a = map_style_layers((80, 60), "rounded", 10, 3, "#123456")
    for _ in range(50):
        assert map_style_layers((80, 60), "rounded", 10, 3, "#123456") is a
    assert _map_style_layers.cache_info().misses == 1
    assert map_style_layers((80, 60), "rounded", 5, 1.5, "#123456", 2) is a
    assert map_style_layers((80, 60), "rounded", 10, 3, "#654321") is not a
    source = Image.new("RGBA", (80, 60), (100, 80, 60, 0))
    assert apply_map_shape(source, "rounded", 10).getchannel("A").getextrema() == (0, 0)


def test_gui_accepts_zero_radius_and_persisted_shape_names():
    from src.gui.qt.models import map_indicator_fields
    fields = {f.name: f for f in map_indicator_fields()}
    assert fields["map_corner_radius"].min_val == 0
    assert {v[0] for v in fields["map_shape"].choices} == {"square", "rectangle", "rounded", "round"}

