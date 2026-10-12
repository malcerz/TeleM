"""Compare old Pillow (SS 2x + Lanczos) vs new OpenCV (fillPoly LINE_AA shift=4) needle rasterization.

Rigorously measures:
- max_diff
- MAE (Mean Absolute Error)
- different_pixels count and ratio
- bounding box of differences
Across all angles (0, 1, 45, 90, 180, 270, 359, fractional angles), needle widths, 1080p and 4K.
"""

from __future__ import annotations
import math
import json
from pathlib import Path
import numpy as np
from PIL import Image, ImageDraw
import cv2

def parse_hex_color(hex_str: str) -> tuple[int, int, int]:
    if not hex_str or not isinstance(hex_str, str):
        return (255, 255, 255)
    s = hex_str.strip().lstrip("#")
    if len(s) == 3:
        s = "".join(c * 2 for c in s)
    if len(s) != 6:
        return (255, 255, 255)
    try:
        return (int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16))
    except ValueError:
        return (255, 255, 255)


def render_needle_old_pillow(
    pts: list[tuple[float, float]],
    bx0: int, by0: int, bw: int, bh: int,
    cfg: dict,
    needle_fill: tuple[int, int, int, int],
) -> Image.Image:
    """Old implementation from Etap 4E/4D: Supersampling 2x + Image.LANCZOS."""
    scale = 2
    patch = Image.new("RGBA", (bw * scale, bh * scale), (0, 0, 0, 0))
    d = ImageDraw.Draw(patch)
    local_poly = [((p[0] - bx0) * scale, (p[1] - by0) * scale) for p in pts]

    n_shadow_enabled = bool(cfg.get("shadow_enabled", False))
    n_outline_enabled = bool(cfg.get("outline_enabled", False))
    n_out_w = float(cfg.get("outline_width", 2.0)) if n_outline_enabled else 0.0
    s_dist = float(cfg.get("shadow_distance", 3.0)) if n_shadow_enabled else 0.0
    s_len = float(cfg.get("shadow_length", 0.0)) if n_shadow_enabled else 0.0
    s_angle = float(cfg.get("shadow_angle", 45.0))
    s_rad = math.radians(s_angle)

    # Needle shadow
    if n_shadow_enabled:
        shad_op_raw = float(cfg.get("shadow_opacity", 0.7))
        shad_op = (shad_op_raw / 100.0) if shad_op_raw > 1.0 else max(0.0, min(1.0, shad_op_raw))
        shad_fade_raw = float(cfg.get("shadow_fade", 1.0))
        shad_fade = (shad_fade_raw / 100.0) if shad_fade_raw > 1.0 else max(0.0, min(1.0, shad_fade_raw))
        s_col = parse_hex_color(cfg.get("shadow_color", "#000000")) or (0, 0, 0)
        if shad_op > 0.0:
            steps = max(1, int(round(s_len))) if s_len > 0.0 else 0
            for step in range(steps, -1, -1):
                fraction = (step / steps) if s_len > 0.0 else 0.0
                reach = s_dist + s_len * fraction
                step_dx = math.cos(s_rad) * reach * scale
                step_dy = math.sin(s_rad) * reach * scale
                weight = max(0.0, 1.0 - shad_fade * fraction) * shad_op
                step_alpha = int(round(weight * 255))
                if step_alpha > 0:
                    poly_step = [(px + step_dx, py + step_dy) for px, py in local_poly]
                    d.polygon(poly_step, fill=(*s_col[:3], step_alpha))

    # Needle outline
    if n_outline_enabled and n_out_w > 0.0:
        out_op_raw = float(cfg.get("outline_opacity", 1.0))
        out_op = (out_op_raw / 100.0) if out_op_raw > 1.0 else max(0.0, min(1.0, out_op_raw))
        out_col = parse_hex_color(cfg.get("outline_color", "#000000")) or (0, 0, 0)
        out_alpha = int(round(out_op * 255))
        if out_alpha > 0:
            stroke_w = max(1, int(round(n_out_w * scale)))
            d.line(local_poly + [local_poly[0]], fill=(*out_col[:3], out_alpha), width=stroke_w * 2, joint="curve")

    # Needle core
    d.polygon(local_poly, fill=needle_fill[:3] + (255,))

    patch_down = patch.resize((bw, bh), Image.LANCZOS)
    return patch_down


def render_needle_new_opencv(
    pts: list[tuple[float, float]],
    bx0: int, by0: int, bw: int, bh: int,
    cfg: dict,
    needle_fill: tuple[int, int, int, int],
) -> Image.Image:
    """New implementation from Etap 5A: OpenCV fillPoly + polylines LINE_AA shift=4."""
    shift = 4
    scale_sub = 1 << shift
    sub_poly = np.array([[[int(round((p[0] - bx0) * scale_sub)), int(round((p[1] - by0) * scale_sub))] for p in pts]], dtype=np.int32)
    patch_cv = np.zeros((bh, bw, 4), dtype=np.uint8)

    n_shadow_enabled = bool(cfg.get("shadow_enabled", False))
    n_outline_enabled = bool(cfg.get("outline_enabled", False))
    n_out_w = float(cfg.get("outline_width", 2.0)) if n_outline_enabled else 0.0
    s_dist = float(cfg.get("shadow_distance", 3.0)) if n_shadow_enabled else 0.0
    s_len = float(cfg.get("shadow_length", 0.0)) if n_shadow_enabled else 0.0
    s_angle = float(cfg.get("shadow_angle", 45.0))
    s_rad = math.radians(s_angle)

    # Needle shadow
    if n_shadow_enabled:
        shad_op_raw = float(cfg.get("shadow_opacity", 0.7))
        shad_op = (shad_op_raw / 100.0) if shad_op_raw > 1.0 else max(0.0, min(1.0, shad_op_raw))
        shad_fade_raw = float(cfg.get("shadow_fade", 1.0))
        shad_fade = (shad_fade_raw / 100.0) if shad_fade_raw > 1.0 else max(0.0, min(1.0, shad_fade_raw))
        s_col = parse_hex_color(cfg.get("shadow_color", "#000000")) or (0, 0, 0)
        if shad_op > 0.0:
            steps = max(1, int(round(s_len))) if s_len > 0.0 else 0
            for step in range(steps, -1, -1):
                fraction = (step / steps) if s_len > 0.0 else 0.0
                reach = s_dist + s_len * fraction
                step_dx = int(round(math.cos(s_rad) * reach * scale_sub))
                step_dy = int(round(math.sin(s_rad) * reach * scale_sub))
                weight = max(0.0, 1.0 - shad_fade * fraction) * shad_op
                step_alpha = int(round(weight * 255))
                if step_alpha > 0:
                    cv2.fillPoly(patch_cv, sub_poly + [step_dx, step_dy], (*s_col[:3], step_alpha), lineType=cv2.LINE_AA, shift=shift)

    # Needle outline
    if n_outline_enabled and n_out_w > 0.0:
        out_op_raw = float(cfg.get("outline_opacity", 1.0))
        out_op = (out_op_raw / 100.0) if out_op_raw > 1.0 else max(0.0, min(1.0, out_op_raw))
        out_col = parse_hex_color(cfg.get("outline_color", "#000000")) or (0, 0, 0)
        out_alpha = int(round(out_op * 255))
        if out_alpha > 0:
            stroke_w = max(1, int(round(n_out_w)))
            cv2.polylines(patch_cv, sub_poly, True, (*out_col[:3], out_alpha), thickness=stroke_w * 2, lineType=cv2.LINE_AA, shift=shift)

    # Needle core
    cv2.fillPoly(patch_cv, sub_poly, (*needle_fill[:3], 255), lineType=cv2.LINE_AA, shift=shift)
    return Image.fromarray(patch_cv)


def run_single_comparison(
    angle_deg: float,
    canvas_w: int, canvas_h: int,
    needle_w_px: int,
    cfg: dict,
) -> dict:
    ang = math.radians(angle_deg)
    radius = int(min(canvas_w, canvas_h) * 0.25)
    _cx, _cy = canvas_w // 2, canvas_h // 2
    needle_len_rel = cfg.get("needle_length", 1.1)
    needle_r_out = max(2, int(radius * needle_len_rel))
    needle_r_in = max(1, int(radius * 0.05))

    pdx, pdy = -math.sin(ang), math.cos(ang)
    tip_x = _cx + math.cos(ang) * needle_r_out
    tip_y = _cy + math.sin(ang) * needle_r_out
    base_x = _cx + math.cos(ang) * needle_r_in
    base_y = _cy + math.sin(ang) * needle_r_in

    _n_hw = needle_w_px / 2.0
    p1 = (base_x + pdx * _n_hw, base_y + pdy * _n_hw)
    p2 = (base_x - pdx * _n_hw, base_y - pdy * _n_hw)
    p3 = (tip_x, tip_y)
    pts = [p1, p2, p3]

    n_outline_enabled = bool(cfg.get("outline_enabled", False))
    n_shadow_enabled = bool(cfg.get("shadow_enabled", False))
    n_out_w = float(cfg.get("outline_width", 2.0)) if n_outline_enabled else 0.0
    s_dist = float(cfg.get("shadow_distance", 3.0)) if n_shadow_enabled else 0.0
    s_len = float(cfg.get("shadow_length", 0.0)) if n_shadow_enabled else 0.0
    s_reach = s_dist + s_len
    s_angle = float(cfg.get("shadow_angle", 45.0))
    s_rad = math.radians(s_angle)

    all_x = [p[0] for p in pts]
    all_y = [p[1] for p in pts]
    if n_shadow_enabled and s_reach > 0.0:
        all_x.extend([p[0] + math.cos(s_rad) * s_reach for p in pts])
        all_y.extend([p[1] + math.sin(s_rad) * s_reach for p in pts])

    _n_margin = 6.0 + (s_reach if n_shadow_enabled else 0.0) + (n_out_w * 2.0 if n_outline_enabled else 0.0)
    bx0 = max(0, int(math.floor(min(all_x) - _n_margin)))
    by0 = max(0, int(math.floor(min(all_y) - _n_margin)))
    bx1 = min(canvas_w, int(math.ceil(max(all_x) + _n_margin)))
    by1 = min(canvas_h, int(math.ceil(max(all_y) + _n_margin)))
    bw, bh = bx1 - bx0, by1 - by0

    needle_rgb = parse_hex_color(cfg.get("needle_color", "#DC3232"))
    needle_fill = (*needle_rgb, 255)

    old_img = render_needle_old_pillow(pts, bx0, by0, bw, bh, cfg, needle_fill)
    new_img = render_needle_new_opencv(pts, bx0, by0, bw, bh, cfg, needle_fill)

    old_arr = np.array(old_img, dtype=np.int32)
    new_arr = np.array(new_img, dtype=np.int32)

    diff = np.abs(old_arr - new_arr)
    max_diff = int(np.max(diff))
    mae = float(np.mean(diff))

    diff_pixels_mask = np.any(diff > 0, axis=-1)
    diff_count = int(np.sum(diff_pixels_mask))
    total_pixels = bw * bh
    diff_pct = (diff_count / total_pixels) * 100.0 if total_pixels > 0 else 0.0

    if diff_count > 0:
        ys, xs = np.where(diff_pixels_mask)
        diff_bbox = [int(np.min(xs)), int(np.min(ys)), int(np.max(xs)), int(np.max(ys))]
    else:
        diff_bbox = None

    return {
        "angle_deg": angle_deg,
        "res": f"{canvas_w}x{canvas_h}",
        "needle_w": needle_w_px,
        "max_diff": max_diff,
        "mae": round(mae, 4),
        "diff_count": diff_count,
        "total_pixels": total_pixels,
        "diff_pct": round(diff_pct, 2),
        "diff_bbox": diff_bbox,
    }


def main():
    test_angles = [0.0, 1.0, 45.0, 90.0, 180.0, 270.0, 359.0, 12.34, 123.45, 234.56]
    resolutions = [(1920, 1080), (3840, 2160)]
    widths = [2, 4, 8]
    cfgs = [
        {"name": "plain", "outline_enabled": False, "shadow_enabled": False},
        {"name": "with_shadow_outline_fade", "outline_enabled": True, "outline_width": 2.0, "shadow_enabled": True, "shadow_distance": 3.0, "shadow_length": 5.0, "shadow_fade": 0.8},
    ]

    results = []
    print(f"{'Angle':>7} | {'Res':>10} | {'W':>2} | {'Cfg':>15} | {'MaxDiff':>7} | {'MAE':>7} | {'DiffPix':>7} | {'Diff%':>6} | {'DiffBBox'}")
    print("-" * 85)

    for cfg in cfgs:
        for res_w, res_h in resolutions:
            for w in widths:
                for ang in test_angles:
                    res = run_single_comparison(ang, res_w, res_h, w, cfg)
                    res["cfg_name"] = cfg["name"]
                    results.append(res)
                    bbox_str = str(res['diff_bbox']) if res['diff_bbox'] else "None"
                    print(f"{ang:7.2f} | {res['res']:>10} | {w:2d} | {cfg['name'][:15]:>15} | {res['max_diff']:7d} | {res['mae']:7.4f} | {res['diff_count']:7d} | {res['diff_pct']:5.2f}% | {bbox_str}")

    out_path = Path(r"C:\_DEV\_SPORTCAMHUD_ETAP_5A_RESULTS_20261012\gauge_needle_parity_study.json")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)
    print(f"\nSaved full results to {out_path}")

if __name__ == "__main__":
    main()
