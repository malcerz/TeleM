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

def test_exact(angle):
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
    
    # Pillow rotate matrix for angle:
    # rad = -math.radians(angle)
    # a_mat = cos(rad), b_mat = sin(rad), d_mat = -sin(rad), e_mat = cos(rad)
    rad = -math.radians(angle)
    a_mat = round(math.cos(rad), 15)
    b_mat = round(math.sin(rad), 15)
    d_mat = round(-math.sin(rad), 15)
    e_mat = round(math.cos(rad), 15)
    
    # In pad_img.rotate, center is (309, 309).
    # For a point (xd, yd) in pad_img, source in pad_img is:
    # xs = a_mat * (xd - 309) + b_mat * (yd - 309) + 309
    # ys = d_mat * (xd - 309) + e_mat * (yd - 309) + 309
    #
    # Source in graphic is:
    # x_graphic = xs - gx = a_mat * (xd - 309) + b_mat * (yd - 309) + 309 - gx
    # y_graphic = ys - gy = d_mat * (xd - 309) + e_mat * (yd - 309) + 309 - gy
    # Since gx = int(round(pad/2 - pivot_px)) = 309 - pivot_px,
    # 309 - gx = pivot_px
    # 309 - gy = pivot_py
    # So:
    # x_graphic = a_mat * (xd - 309) + b_mat * (yd - 309) + pivot_px
    # y_graphic = d_mat * (xd - 309) + e_mat * (yd - 309) + pivot_py
    
    # Forward mapping to find bounding box of graphic corners in pad_img:
    # Inverse of matrix [[a_mat, b_mat], [d_mat, e_mat]]:
    # Since it's a rotation, inverse is transpose:
    # (xd - 309) = a_mat * (xs - 309) + d_mat * (ys - 309)
    # (yd - 309) = b_mat * (xs - 309) + e_mat * (ys - 309)
    # where (xs - 309) = (x_graphic - pivot_px), (ys - 309) = (y_graphic - pivot_py)
    
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
    margin = 3
    xd0 = max(0, int(math.floor(min_xd)) - margin)
    yd0 = max(0, int(math.floor(min_yd)) - margin)
    xd1 = min(pad, int(math.ceil(max_xd)) + margin)
    yd1 = min(pad, int(math.ceil(max_yd)) + margin)
    
    tw = xd1 - xd0
    th = yd1 - yd0
    
    # In tight image (u, v):
    # xd = u + xd0, yd = v + yd0
    # x_graphic = a_mat * (u + xd0 - 309) + b_mat * (v + yd0 - 309) + pivot_px
    #           = a_mat * u + b_mat * v + [ a_mat * (xd0 - 309) + b_mat * (yd0 - 309) + pivot_px ]
    # y_graphic = d_mat * u + e_mat * v + [ d_mat * (xd0 - 309) + e_mat * (yd0 - 309) + pivot_py ]
    
    c_x = a_mat * (xd0 - 309.0) + b_mat * (yd0 - 309.0) + pivot_px
    c_y = d_mat * (xd0 - 309.0) + e_mat * (yd0 - 309.0) + pivot_py
    
    matrix = (a_mat, b_mat, c_x, d_mat, e_mat, c_y)
    
    tight_img = graphic.transform(
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
    if diff_cnt > 0:
        diff_locs = np.argwhere(diff > 0)
        print(f"   diff max: {max_d}, locations count: {len(diff_locs)}, sample diff: {diff[diff_locs[0][0], diff_locs[0][1]]}")

for ang in [-20.0, -14.35, -10.0, -5.0, 0.0, 5.0, 10.0, 15.0, 20.0, 23.65, 24.0]:
    test_exact(ang)
