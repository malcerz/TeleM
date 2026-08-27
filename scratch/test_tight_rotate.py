import math
import sys
import time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import numpy as np
from PIL import Image

# Load the real graphic
from src.indicators.lean import _load_lean_graphic, _graphic_pivot, _rotate_paste_params
from src.indicators.helpers import s

def test_methods():
    cfg = {"graphic": "bike", "pivot_x": 0.5, "pivot_y": 1.0}
    size_px = 307
    graphic = _load_lean_graphic(cfg, size_px)
    gw, gh = graphic.size
    pivot_px, pivot_py = _graphic_pivot(cfg, gw, gh)
    print(f"Graphic size: {gw}x{gh}, pivot: ({pivot_px}, {pivot_py})")

    angles = [-20.0, -14.35, -10.0, -5.0, 0.0, 5.0, 10.0, 15.0, 20.0, 23.65, 24.0]
    raster_w, center_y = 323, 194.5

    # Method 0: Reference (618x618)
    def run_ref(angle):
        pad, paste_x, paste_y, sx, sy = _rotate_paste_params(gw, gh, pivot_px, pivot_py, raster_w, center_y)
        pad_img = Image.new("RGBA", (pad, pad), (0, 0, 0, 0))
        pad_img.alpha_composite(
            graphic,
            (int(round(pad / 2.0 - pivot_px)), int(round(pad / 2.0 - pivot_py))),
        )
        rotated = pad_img.rotate(
            angle,
            resample=Image.Resampling.BICUBIC,
        )
        # Composite to final widget raster
        img = Image.new("RGBA", (raster_w, 430), (0, 0, 0, 0))
        img.alpha_composite(rotated, (int(round(paste_x)), int(round(paste_y))))
        return img, (sx, sy)

    # Method 1: Affine transform on tight bounding box
    def run_affine_tight(angle):
        rad = math.radians(-angle) # Pillow angle convention
        cos_a = math.cos(rad)
        sin_a = math.sin(rad)
        
        # Corners of graphic relative to pivot
        corners = [
            (-pivot_px, -pivot_py),
            (gw - pivot_px, -pivot_py),
            (gw - pivot_px, gh - pivot_py),
            (-pivot_px, gh - pivot_py),
        ]
        # Rotated corners relative to pivot
        rot_corners = []
        for x, y in corners:
            rx = x * cos_a - y * sin_a
            ry = x * sin_a + y * cos_a
            rot_corners.append((rx, ry))
        
        min_rx = min(c[0] for c in rot_corners)
        max_rx = max(c[0] for c in rot_corners)
        min_ry = min(c[1] for c in rot_corners)
        max_ry = max(c[1] for c in rot_corners)

        # Margin for bicubic filter (2 px on each side)
        margin = 3
        # Bounding box relative to pivot:
        bx0 = math.floor(min_rx) - margin
        by0 = math.floor(min_ry) - margin
        bx1 = math.ceil(max_rx) + margin
        by1 = math.ceil(max_ry) + margin
        
        tw = int(bx1 - bx0)
        th = int(by1 - by0)
        
        # In destination tight image of size (tw, th), destination coord (xd, yd)
        # corresponds to relative-to-pivot position:
        # p_rel = (xd + bx0, yd + by0)
        # To map dst -> src:
        # source_rel_x = p_rel_x * cos(-rad) - p_rel_y * sin(-rad) = p_rel_x * cos_a + p_rel_y * sin_a
        # source_rel_y = -p_rel_x * sin_a + p_rel_y * cos_a
        # In Pillow affine transform:
        # x_src = a * xd + b * yd + c
        # y_src = d * xd + e * yd + f
        # where (x_src, y_src) is relative to graphic (0, 0).
        # x_src = pivot_px + (xd + bx0) * cos_a + (yd + by0) * sin_a
        # y_src = pivot_py - (xd + bx0) * sin_a + (yd + by0) * cos_a
        # So:
        # a = cos_a, b = sin_a, c = pivot_px + bx0 * cos_a + by0 * sin_a
        # d = -sin_a, e = cos_a, f = pivot_py - bx0 * sin_a + by0 * cos_a
        
        c = pivot_px + bx0 * cos_a + by0 * sin_a
        f = pivot_py - bx0 * sin_a + by0 * cos_a
        matrix = (cos_a, sin_a, c, -sin_a, cos_a, f)
        
        tight_rot = graphic.transform(
            (tw, th),
            Image.Transform.AFFINE,
            matrix,
            resample=Image.Resampling.BICUBIC,
        )
        
        # Screen position of pivot:
        sx = raster_w / 2.0 + (pivot_px - gw / 2.0)
        sy = center_y + (pivot_py - gh / 2.0)
        
        # Destination placement of tight_rot:
        # since (xd=0, yd=0) corresponds to offset (bx0, by0) from pivot:
        dest_x = int(round(sx + bx0))
        dest_y = int(round(sy + by0))
        
        img = Image.new("RGBA", (raster_w, 430), (0, 0, 0, 0))
        # Note: handle clipping if dest_x or dest_y is negative or extends past raster
        # But alpha_composite can paste at (dest_x, dest_y) directly if within bounds or clipped
        # Let's check clipping:
        if dest_x < 0 or dest_y < 0 or dest_x + tw > raster_w or dest_y + th > 430:
            # clip if needed
            cx0 = max(0, dest_x)
            cy0 = max(0, dest_y)
            cx1 = min(raster_w, dest_x + tw)
            cy1 = min(430, dest_y + th)
            if cx1 > cx0 and cy1 > cy0:
                cropped = tight_rot.crop((cx0 - dest_x, cy0 - dest_y, cx1 - dest_x, cy1 - dest_y))
                img.alpha_composite(cropped, (cx0, cy0))
        else:
            img.alpha_composite(tight_rot, (dest_x, dest_y))
            
        return img, (sx, sy), (tw, th)

    # Let's benchmark and compare parity across all angles
    print("\n--- TESTING ANGLES ---")
    for ang in angles:
        ref_img, ref_p = run_ref(ang)
        cand_img, cand_p, size = run_affine_tight(ang)
        
        ref_arr = np.array(ref_img)
        cand_arr = np.array(cand_img)
        
        diff = np.abs(ref_arr.astype(int) - cand_arr.astype(int))
        max_diff = np.max(diff)
        diff_count = np.count_nonzero(diff)
        mae = np.mean(diff)
        
        print(f"Angle {ang:+6.2f}°: tight size={size[0]}x{size[1]} | max_diff={max_diff:3d}, diff_pixels={diff_count:5d}, MAE={mae:.4f}")

if __name__ == "__main__":
    test_methods()
