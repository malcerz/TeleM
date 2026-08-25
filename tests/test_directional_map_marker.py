from PIL import Image

from src.moving_map import draw_position_marker


def _tip(image):
    px = image.load()
    points = [(x, y) for y in range(image.height) for x in range(image.width)
              if px[x, y][3] and px[x, y][:3] == (255, 255, 255)]
    return min(points, key=lambda p: p[1]), max(points, key=lambda p: p[1])


def test_default_dot_and_missing_heading_fall_back_to_legacy_marker():
    dot = Image.new("RGBA", (41, 41), (0, 0, 0, 0))
    missing = Image.new("RGBA", (41, 41), (0, 0, 0, 0))
    draw_position_marker(dot, (20, 20), 6, style="dot")
    draw_position_marker(missing, (20, 20), 6, style="directional", heading=None)
    assert dot.tobytes() == missing.tobytes()


def test_north_up_direction_changes_with_heading_and_stays_centered():
    north = Image.new("RGBA", (51, 51), (0, 0, 0, 0))
    east = Image.new("RGBA", (51, 51), (0, 0, 0, 0))
    draw_position_marker(north, (25, 25), 7, style="directional", heading=0)
    draw_position_marker(east, (25, 25), 7, style="directional", heading=90)
    assert _tip(north)[0][1] < 25
    assert max((x for x, y in [(x, y) for y in range(51) for x in range(51)
                               if east.getpixel((x, y))[:3] == (255, 255, 255)])) > 25
