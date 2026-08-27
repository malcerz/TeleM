import math
import sys
from PIL import Image, ImageDraw
import numpy as np

def draw_cursor_legacy(image, cursor_x, py, plot_y1, plot_y2, calc_thickness, cursor_color, line_color, offset_x, offset_y, chart_width, chart_height):
    alpha = 200
    post_rgb = tuple((channel * alpha + 127) // 255 for channel in cursor_color)
    post_alpha = (alpha * alpha + 127) // 255
    draw = ImageDraw.Draw(image)
    draw.line(
        (cursor_x, plot_y1 + offset_y, cursor_x, plot_y2 + offset_y),
        fill=(*post_rgb, post_alpha), width=max(2, calc_thickness),
    )
    dot_r = max(3, calc_thickness + 1)
    left = int(math.floor(cursor_x - dot_r))
    top = int(math.floor(py - dot_r))
    right = math.ceil(cursor_x + dot_r) + 1
    bottom = math.ceil(py + dot_r) + 1
    tile = Image.new("RGBA", (right - left, bottom - top), (0, 0, 0, 0))
    tile_draw = ImageDraw.Draw(tile)
    tile_draw.ellipse(
        (cursor_x - dot_r - left, py - dot_r - top,
         cursor_x + dot_r - left, py + dot_r - top),
        fill=(*cursor_color, 255), outline=(*line_color, 255),
    )
    clip_left, clip_top = offset_x, offset_y
    clip_right, clip_bottom = offset_x + chart_width, offset_y + chart_height
    dst_left, dst_top = max(left, clip_left), max(top, clip_top)
    dst_right, dst_bottom = min(right, clip_right), min(bottom, clip_bottom)
    if dst_right > dst_left and dst_bottom > dst_top:
        clipped = tile.crop((
            dst_left - left, dst_top - top, dst_right - left, dst_bottom - top,
        ))
        image.paste(clipped, (dst_left, dst_top), clipped)

def draw_cursor_direct(image, cursor_x, py, plot_y1, plot_y2, calc_thickness, cursor_color, line_color, offset_x, offset_y, chart_width, chart_height):
    alpha = 200
    post_rgb = tuple((channel * alpha + 127) // 255 for channel in cursor_color)
    post_alpha = (alpha * alpha + 127) // 255
    draw = ImageDraw.Draw(image)
    draw.line(
        (cursor_x, plot_y1 + offset_y, cursor_x, plot_y2 + offset_y),
        fill=(*post_rgb, post_alpha), width=max(2, calc_thickness),
    )
    dot_r = max(3, calc_thickness + 1)
    # Direct draw of opaque ellipse with clipping bounds check
    left = int(math.floor(cursor_x - dot_r))
    top = int(math.floor(py - dot_r))
    right = math.ceil(cursor_x + dot_r) + 1
    bottom = math.ceil(py + dot_r) + 1
    clip_left, clip_top = offset_x, offset_y
    clip_right, clip_bottom = offset_x + chart_width, offset_y + chart_height
    # If entirely within chart bounds, draw directly onto image without any intermediate Image allocation
    if left >= clip_left and top >= clip_top and right <= clip_right and bottom <= clip_bottom:
        draw.ellipse(
            (cursor_x - dot_r, py - dot_r, cursor_x + dot_r, py + dot_r),
            fill=(*cursor_color, 255), outline=(*line_color, 255),
        )
    else:
        tile = Image.new("RGBA", (right - left, bottom - top), (0, 0, 0, 0))
        tile_draw = ImageDraw.Draw(tile)
        tile_draw.ellipse(
            (cursor_x - dot_r - left, py - dot_r - top,
             cursor_x + dot_r - left, py + dot_r - top),
            fill=(*cursor_color, 255), outline=(*line_color, 255),
        )
        dst_left, dst_top = max(left, clip_left), max(top, clip_top)
        dst_right, dst_bottom = min(right, clip_right), min(bottom, clip_bottom)
        if dst_right > dst_left and dst_bottom > dst_top:
            clipped = tile.crop((
                dst_left - left, dst_top - top, dst_right - left, dst_bottom - top,
            ))
            image.paste(clipped, (dst_left, dst_top), clipped)

print("=" * 90)
print("TESTING CURSOR DIRECT DRAW PARITY OVER 1000 RANDOM SUBPIXEL POSITIONS")
print("=" * 90)

max_diff = 0
for i in range(1000):
    img_ref = Image.new("RGBA", (400, 200), (30, 40, 50, 100))
    img_cand = Image.new("RGBA", (400, 200), (30, 40, 50, 100))
    cx = 20.0 + (i * 0.37) % 350.0
    cy = 20.0 + (i * 0.51) % 150.0
    
    draw_cursor_legacy(img_ref, cx, cy, 10, 190, 2, (255, 255, 255), (255, 0, 0), 4, 10, 390, 180)
    draw_cursor_direct(img_cand, cx, cy, 10, 190, 2, (255, 255, 255), (255, 0, 0), 4, 10, 390, 180)
    
    arr_ref = np.array(img_ref)
    arr_cand = np.array(img_cand)
    diff = np.max(np.abs(arr_ref.astype(int) - arr_cand.astype(int)))
    if diff > max_diff:
        max_diff = diff

print(f"Max pixel difference: {max_diff}")
assert max_diff == 0, f"Parity failed with max_diff={max_diff}"
print("CURSOR DIRECT DRAW: 100% BIT-FOR-BIT EXACT PARITY!")
