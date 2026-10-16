"""Exact raster contract for the existing Pillow Track-Up filter and marker."""
import numpy as np
import pytest
from PIL import Image, ImageDraw

from src.moving_map import (
    MovingMapRenderer, _rotate_track_up_viewport, track_up_working_size,
)


@pytest.mark.parametrize("output", [64, 255, 499])
@pytest.mark.parametrize("opaque", [False, True])
def test_viewport_matches_rotate_then_crop_for_fractional_and_cardinal_angles(output, opaque):
    working = track_up_working_size(output)
    rng = np.random.default_rng(output)
    pixels = rng.integers(0, 256, (working, working, 4), dtype=np.uint8)
    if opaque:
        pixels[..., 3] = 255
    image = Image.fromarray(pixels)
    original = image.tobytes()
    offset = (working - output) // 2
    for angle in [0., .01, 1., 30., 45., 73.123, 90., 95., 180., 270., 359., 359.99]:
        reference = image.rotate(angle, Image.Resampling.BICUBIC, expand=False, fillcolor=(30, 30, 30, 255))
        reference = reference.crop((offset, offset, offset + output, offset + output))
        assert _rotate_track_up_viewport(image, angle, output).tobytes() == reference.tobytes(), angle
    assert image.tobytes() == original


@pytest.mark.parametrize("output", [64, 255, 499])
def test_directional_marker_keeps_exact_float_origin_and_return_has_no_ghosting(output):
    class Renderer:
        _mkr_style = "directional"
        _mkr_radius = 7
        _mkr_color = (255, 255, 255, 255)
        def render(self, ts, w, h, **kwargs):
            image = Image.new("RGBA", (w, h), (20, 60, 90, 255))
            ImageDraw.Draw(image).line((ts, 0, w // 2, h), fill=(250, 50, 30, 220), width=5)
            return image
    renderer = Renderer()
    for angle in [1., 45., 90., 180., 270., 359.]:
        working = track_up_working_size(output)
        source = renderer.render(3, working, working)
        ref = source.rotate(angle, Image.Resampling.BICUBIC, expand=False, fillcolor=(30, 30, 30, 255))
        center, r = working / 2., renderer._mkr_radius
        ImageDraw.Draw(ref).polygon(((center, center-r*1.8), (center-r*.65, center+r*.75),
                                    (center+r*.65, center+r*.75)), fill=renderer._mkr_color, outline=(0, 0, 0, 220))
        offset = (working - output) // 2
        ref = ref.crop((offset, offset, offset + output, offset + output))
        a = MovingMapRenderer.render_track_up(renderer, 3, output, heading=angle)
        MovingMapRenderer.render_track_up(renderer, 8, output, heading=angle)
        b = MovingMapRenderer.render_track_up(renderer, 3, output, heading=angle)
        assert a.tobytes() == b.tobytes() == ref.tobytes()
