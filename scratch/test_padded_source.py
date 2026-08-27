import math
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import numpy as np
from PIL import Image

from src.indicators.lean import _load_lean_graphic, _graphic_pivot, _rotate_paste_params

cfg = {"graphic": "bike", "pivot_x": 0.5, "pivot_y": 1.0}
size_px = 307
graphic = _load_lean_graphic(cfg, size_px)
gw, gh = graphic.size
pivot_px, pivot_py = _graphic_pivot(cfg, gw, gh)
raster_w, center_y = 323, 194.5

# What if we cache a source with e.g. 4px padding around graphic?
pad_src_margin = 4
padded_graphic = Image.new("RGBA", (gw + 2 * pad_src_margin, gh + 2 * pad_src_margin), (0, 0, 0, 0))
padded_graphic.alpha_composite(graphic, (pad_src_margin, pad_src_margin))
pgw, pgh = padded_graphic.size
ppivot_px = pivot_px + pad_src_margin
ppivot_py = pivot_py + pad_src_margin

def test_padded_source(angle):
    # Reference
    pad, paste_x, paste_y, sx, sy = _rotate_paste_params(gw, gh, pivot_px, pivot_py, raster_w, center_y)
    pad_img = Image.new("RGBA", (pad, pad), (0, 0, 0, 0))
    gx = int(round(pad / 2.0 - pivot_px))
    gy = int(round(pad / 2.0 - pivot_py))
    pad_img.alpha_composite(graphic, (gx, gy))
    rotated = pad_img.rotate(angle, resample=Image.Resampling.BICUBIC)
    
    ref_img = Image.new("RGBA", (raster_w, 430), (0, 0, 0, 0))
    px = int(round(paste_x))
    py = int(round(paste_y))
    ref_img.alpha_composite(rotated, (px, py))
    
    rad = -math.radians(angle)
    a_mat = round(math.cos(rad), 15)
    b_mat = round(math.sin(rad), 15)
    d_mat = round(-math.sin(rad), 15)
    e_mat = round(math.cos(rad), 15)
    
    corners_rel = [
        (-pivot_px, -pivot_py),
        (gw - pivot_px, -pivot_py),
        (gw - pivot_px, gh - pivot_py),
        (-pivot_px, gh - pivot_py),
    ]
    
    rot_c = []
    for xg_rel, yg_rel in corners_rel:
        xd_rel = a_mat * xg_rel + d_mat * yg_rel
        yd_rel = b_mat * xg_rel + e_mat * yg_rel
        rot_c.append((xd_rel + 309.0, yd_rel + 309.0))
        
    min_xd = min(c[0] for c in rot_c)
    max_xd = max(c[0] for c in rot_c)
    min_yd = min(c[1] for c in rot_c)
    max_yd = max(c[1] for c in rot_c)
    
    # Margin for bicubic filter
    margin = 4
    xd0 = max(0, int(math.floor(min_xd)) - margin)
    yd0 = max(0, int(math.floor(min_yd)) - margin)
    xd1 = min(pad, int(math.ceil(max_xd)) + margin)
    yd1 = min(pad, int(math.ceil(max_yd)) + margin)
    
    tw = xd1 - xd0
    th = yd1 - yd0
    
    c_x = a_mat * (xd0 - 309.0) + b_mat * (yd0 - 309.0) + ppivot_px
    c_y = d_mat * (xd0 - 309.0) + e_mat * (yd0 - 309.0) + ppivot_py
    
    matrix = (a_mat, b_mat, c_x, d_mat, e_mat, c_y)
    
    tight_img = padded_graphic.transform(
        (tw, th),
        Image.Transform.AFFINE,
        matrix,
        resample=Image.Resampling.BICUBIC,
    )
    
    cand_img = Image.new("RGBA", (raster_w, 430), (0, 0, 0, 0))
    dest_x = px + xd0
    dest_y = py + yd0
    
    cx0 = max(0, dest_x)
    cy0 = max(0, dest_y)
    cx1 = min(raster_w, dest_x + tw)
    cy1 = min(430, dest_y + th)
    if cx1 > cx0 and cy1 > cy0:
        if (cx0, cy0, cx1, cy1) == (dest_x, dest_y, dest_x + tw, dest_y + th):
            cand_img.alpha_composite(tight_img, (dest_x, dest_y))
        else:
            cropped = tight_img.crop((cx0 - dest_x, cy0 - dest_y, cx1 - dest_x, cy1 - dest_y))
            cand_img.alpha_composite(cropped, (cx0, cy0))
            
    diff = np.abs(np.array(ref_img).astype(int) - np.array(cand_img).astype(int))
    max_d = np.max(diff)
    diff_cnt = np.count_nonzero(diff)
    mae = np.mean(diff)
    print(f"Angle {angle:+6.2f}°: tight size {tw}x{th} -> max_diff={max_d:3d}, diff_pixels={diff_cnt:5d}, MAE={mae:.6f}")

for ang in [-20.0, -14.35, -10.0, -5.0, 0.0, 5.0, 10.0, 15.0, 20.0, 23.65, 24.0]:
    test_padded_source(ang)
