import math
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import numpy as np
from PIL import Image

from src.indicators.lean import _load_lean_graphic, _graphic_pivot, _rotate_paste_params

def verify_general_parity(cfg, size_px, angles):
    graphic = _load_lean_graphic(cfg, size_px)
    gw, gh = graphic.size
    pivot_px, pivot_py = _graphic_pivot(cfg, gw, gh)
    raster_w, center_y = 400, 250.0
    raster_h = 500
    
    # Pre-pad graphic source
    pad_margin = 4
    padded_graphic = Image.new("RGBA", (gw + 2 * pad_margin, gh + 2 * pad_margin), (0, 0, 0, 0))
    padded_graphic.alpha_composite(graphic, (pad_margin, pad_margin))
    
    pad_ref, paste_x_ref, paste_y_ref, sx_ref, sy_ref = _rotate_paste_params(gw, gh, pivot_px, pivot_py, raster_w, center_y)
    px_ref = int(round(paste_x_ref))
    py_ref = int(round(paste_y_ref))
    gx_ref = int(round(pad_ref / 2.0 - pivot_px))
    gy_ref = int(round(pad_ref / 2.0 - pivot_py))
    Cx = pad_ref / 2.0
    Cy = pad_ref / 2.0
    delta_gx = Cx - gx_ref
    delta_gy = Cy - gy_ref
    Px = delta_gx + pad_margin
    Py = delta_gy + pad_margin
    
    corners_src_rel = [
        (gx_ref - Cx, gy_ref - Cy),
        (gx_ref + gw - Cx, gy_ref - Cy),
        (gx_ref + gw - Cx, gy_ref + gh - Cy),
        (gx_ref - Cx, gy_ref + gh - Cy),
    ]
    
    for ang in angles:
        # Reference
        pad_img = Image.new("RGBA", (pad_ref, pad_ref), (0, 0, 0, 0))
        pad_img.alpha_composite(graphic, (gx_ref, gy_ref))
        rotated = pad_img.rotate(ang, resample=Image.Resampling.BICUBIC)
        ref_img = Image.new("RGBA", (raster_w, raster_h), (0, 0, 0, 0))
        ref_img.alpha_composite(rotated, (px_ref, py_ref))
        
        # Candidate
        cand_img = Image.new("RGBA", (raster_w, raster_h), (0, 0, 0, 0))
        if abs(ang) < 1e-6:
            dest_x = px_ref + gx_ref
            dest_y = py_ref + gy_ref
            # clip if needed
            cx0 = max(0, dest_x)
            cy0 = max(0, dest_y)
            cx1 = min(raster_w, dest_x + gw)
            cy1 = min(raster_h, dest_y + gh)
            if cx1 > cx0 and cy1 > cy0:
                if (cx0, cy0, cx1, cy1) == (dest_x, dest_y, dest_x + gw, dest_y + gh):
                    cand_img.alpha_composite(graphic, (dest_x, dest_y))
                else:
                    cand_img.alpha_composite(graphic.crop((cx0 - dest_x, cy0 - dest_y, cx1 - dest_x, cy1 - dest_y)), (cx0, cy0))
        else:
            rad = -math.radians(ang)
            a_mat = round(math.cos(rad), 15)
            b_mat = round(math.sin(rad), 15)
            d_mat = round(-math.sin(rad), 15)
            e_mat = round(math.cos(rad), 15)
            
            rot_c = [
                (a_mat * u + d_mat * v + Cx, b_mat * u + e_mat * v + Cy)
                for u, v in corners_src_rel
            ]
            min_xd = min(c[0] for c in rot_c)
            max_xd = max(c[0] for c in rot_c)
            min_yd = min(c[1] for c in rot_c)
            max_yd = max(c[1] for c in rot_c)
            
            margin = 4
            xd0 = max(0, int(math.floor(min_xd)) - margin)
            yd0 = max(0, int(math.floor(min_yd)) - margin)
            xd1 = min(pad_ref, int(math.ceil(max_xd)) + margin)
            yd1 = min(pad_ref, int(math.ceil(max_yd)) + margin)
            
            tw = xd1 - xd0
            th = yd1 - yd0
            
            c_x = a_mat * (xd0 - Cx) + b_mat * (yd0 - Cy) + Px
            c_y = d_mat * (xd0 - Cx) + e_mat * (yd0 - Cy) + Py
            matrix = (a_mat, b_mat, c_x, d_mat, e_mat, c_y)
            
            tight_img = padded_graphic.transform(
                (tw, th),
                Image.Transform.AFFINE,
                matrix,
                resample=Image.Resampling.BICUBIC,
            )
            dest_x = px_ref + xd0
            dest_y = py_ref + yd0
            
            cx0 = max(0, dest_x)
            cy0 = max(0, dest_y)
            cx1 = min(raster_w, dest_x + tw)
            cy1 = min(raster_h, dest_y + th)
            if cx1 > cx0 and cy1 > cy0:
                if (cx0, cy0, cx1, cy1) == (dest_x, dest_y, dest_x + tw, dest_y + th):
                    cand_img.alpha_composite(tight_img, (dest_x, dest_y))
                else:
                    cropped = tight_img.crop((cx0 - dest_x, cy0 - dest_y, cx1 - dest_x, cy1 - dest_y))
                    cand_img.alpha_composite(cropped, (cx0, cy0))
                    
        diff = np.abs(np.array(ref_img).astype(int) - np.array(cand_img).astype(int))
        max_d = np.max(diff)
        diff_cnt = np.count_nonzero(diff)
        assert max_d == 0 and diff_cnt == 0, f"Mismatch for cfg={cfg}, size={size_px}, ang={ang}: max_d={max_d}, diff_cnt={diff_cnt}"

test_configs = [
    ({"graphic": "bike", "pivot_x": 0.5, "pivot_y": 1.0}, 307),
    ({"graphic": "bike", "pivot_x": 0.5, "pivot_y": 0.5}, 150),
    ({"graphic": "beam", "pivot_x": 0.3, "pivot_y": 0.8}, 200),
    ({"graphic": "beam", "pivot_x": 0.0, "pivot_y": 0.0}, 100),
]
angles = [-30.0, -20.0, -14.35, -5.0, 0.0, 5.0, 10.0, 15.0, 23.65, 30.0]

for cfg, sz in test_configs:
    verify_general_parity(cfg, sz, angles)
    print(f"PASS: {cfg['graphic']} size={sz} pivot=({cfg['pivot_x']}, {cfg['pivot_y']}) across all angles")

print("\nALL CONFIGURATIONS ACHIEVE 100% BIT-FOR-BIT EXACT PARITY (max_diff=0, diff_pixels=0)!")
