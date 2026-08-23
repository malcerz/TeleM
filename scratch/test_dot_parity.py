import math
from PIL import Image, ImageDraw
import numpy as np

def old_dot(cursor_x, py, dot_r, cursor_color, line_color):
    left = math.floor(cursor_x - dot_r)
    top = math.floor(py - dot_r)
    right = math.ceil(cursor_x + dot_r) + 1
    bottom = math.ceil(py + dot_r) + 1
    tile = Image.new("RGBA", (right - left, bottom - top), (0, 0, 0, 0))
    tile_draw = ImageDraw.Draw(tile)
    tile_draw.ellipse(
        (cursor_x - dot_r - left, py - dot_r - top,
         cursor_x + dot_r - left, py + dot_r - top),
        fill=(*cursor_color, 255), outline=(*line_color, 255),
    )
    return tile, left, top

_DOT_TILES = {}
def new_dot(cursor_x, py, dot_r, cursor_color, line_color):
    left = int(math.floor(cursor_x - dot_r))
    top = int(math.floor(py - dot_r))
    x0 = cursor_x - dot_r - left
    y0 = py - dot_r - top
    if x0 == 0.0 and y0 == 0.0:
        key = (int(dot_r), tuple(cursor_color), tuple(line_color))
        tile = _DOT_TILES.get(key)
        if tile is None:
            dim = 2 * int(dot_r) + 1
            tile = Image.new("RGBA", (dim, dim), (0, 0, 0, 0))
            d = ImageDraw.Draw(tile)
            d.ellipse((0, 0, 2 * dot_r, 2 * dot_r), fill=(*cursor_color, 255), outline=(*line_color, 255))
            _DOT_TILES[key] = tile
        return tile, left, top
    else:
        # Fallback for subpixel
        return old_dot(cursor_x, py, dot_r, cursor_color, line_color)

# Test various coordinates
for cx in [10.0, 15.0, 100.0, 100.5, 250.25]:
    for cy in [20.0, 35.0, 50.0, 50.5, 80.75]:
        t1, l1, top1 = old_dot(cx, cy, 4, (255, 255, 255), (255, 212, 42))
        t2, l2, top2 = new_dot(cx, cy, 4, (255, 255, 255), (255, 212, 42))
        assert l1 == l2 and top1 == top2
        diff = np.array(t1) - np.array(t2)
        assert np.max(np.abs(diff)) == 0, f"Mismatch at {cx}, {cy}: {np.max(np.abs(diff))}"

print("All dot tile parity tests PASSED!")
