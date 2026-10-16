"""Map pitch must not turn the selected map shape into a trapezoid.

The perspective acts on the map content; the final visible area (alpha silhouette)
for pitch > 0 must equal the silhouette of the same shape at pitch 0."""
import numpy as np
import pytest
from PIL import Image

from src.indicators.helpers import apply_map_pitch, apply_map_shape


def _map(size=400):
    """Opaque synthetic map with a grid (content must change under perspective)."""
    a = np.zeros((size, size, 4), np.uint8)
    a[..., 0] = 0                                    # no red: only the border is red
    a[..., 1] = np.linspace(0, 255, size, dtype=np.uint8)[:, None]
    a[..., 2] = np.linspace(0, 200, size, dtype=np.uint8)[None, :]
    a[::20, :, 2] = 255
    a[:, ::20, 2] = 255
    a[..., 3] = 255
    return Image.fromarray(a, "RGBA")


def _render(shape, pitch, border=0):
    img = apply_map_pitch(_map(), pitch)                      # production order: pitch first
    return apply_map_shape(img, shape, 40, border, "#FF3010", 1.0)


@pytest.mark.parametrize("shape", ["square", "rectangle", "rounded", "round"])
@pytest.mark.parametrize("pitch", [30, 45, 70])
def test_pitch_keeps_selected_shape(shape, pitch):
    flat = np.asarray(_render(shape, 0))
    tilted = np.asarray(_render(shape, pitch))
    # Same final silhouette (no trapezoid): allow 1-pixel antialiasing differences on the edge.
    diff = np.abs(flat[..., 3].astype(int) - tilted[..., 3].astype(int)) > 8
    assert diff.mean() < 0.002, f"{shape} pitch={pitch}: silhouette changed on {diff.mean():.2%} px"
    # Square box corners stay filled for square/rectangle (the old trapezoid left them transparent).
    if shape in ("square", "rectangle"):
        assert tilted[2, 2, 3] == 255 and tilted[2, -3, 3] == 255
    # Perspective is still applied to the content.
    assert np.abs(flat[..., :3].astype(int) - tilted[..., :3].astype(int)).mean() > 5


def test_pitch_zero_is_unchanged():
    img = _map()
    assert apply_map_pitch(img, 0) is img


def test_border_follows_shape_with_pitch():
    flat = np.asarray(_render("rounded", 0, border=6))
    tilted = np.asarray(_render("rounded", 45, border=6))
    red = lambda a: (a[..., 0] > 200) & (a[..., 1] < 90) & (a[..., 2] < 60) & (a[..., 3] > 200)
    assert np.mean(red(flat) != red(tilted)) < 0.003           # border drawn on the final shape
