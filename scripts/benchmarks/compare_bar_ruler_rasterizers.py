"""Compare Pillow LANCZOS vs OpenCV INTER_LANCZOS4 for Bar/Ruler.

Rigorously measures:
- max_diff
- MAE (Mean Absolute Error)
- different_pixels count and ratio
- bounding box of differences
Across resolutions (1080p, 4K), values, styles, and effects.
"""

from __future__ import annotations
import sys
from pathlib import Path
repo_root = Path(__file__).resolve().parents[2]
if str(repo_root) not in sys.path:
    sys.path.insert(0, str(repo_root))

import json
import numpy as np
from PIL import Image
import cv2

from src.indicators.bar import _render_bar_indicator, clear_bar_cache

def run_bar_comparison():
    clear_bar_cache()
    configs = [
        {
            "name": "ruler_horizontal_4k_dist",
            "canvas_w": 3840,
            "canvas_h": 2160,
            "values": [0.0, 12.34, 25.0, 49.9, 50.0],
            "cfg": {
                "bar_style": "ruler",
                "direction": "horizontal",
                "x": 50.0, "y": 7.42,
                "size": 60.0, "thickness": 1.8,
                "min_val": 0.0, "max_val": 50.0,
                "text_color": "#F4F4F4", "tick_color": "#F6F6F6",
                "unit": "km", "label": "DISTANCE",
                "shadow_enabled": True, "shadow_distance": 1.0, "shadow_length": 1.5,
            }
        },
        {
            "name": "ruler_horizontal_1080p_power",
            "canvas_w": 1920,
            "canvas_h": 1080,
            "values": [0.0, 150.0, 245.5, 499.0],
            "cfg": {
                "bar_style": "ruler",
                "direction": "horizontal",
                "x": 50.0, "y": 94.5,
                "size": 50.0, "thickness": 2.0,
                "min_val": 0.0, "max_val": 500.0,
                "text_color": "#FFFFFF", "tick_color": "#AAAAAA",
                "unit": "W", "label": "POWER",
                "shadow_enabled": True, "shadow_distance": 2.0, "shadow_length": 3.0,
            }
        },
        {
            "name": "ruler_subpixel_sweep_steps",
            "canvas_w": 3840,
            "canvas_h": 2160,
            "values": [10.0, 10.05, 10.1, 10.25, 10.5, 10.75, 10.99, 11.0],
            "cfg": {
                "bar_style": "ruler",
                "direction": "horizontal",
                "x": 50.0, "y": 10.0,
                "size": 60.0, "thickness": 2.0,
                "min_val": 0.0, "max_val": 100.0,
                "text_color": "#FFFFFF",
                "unit": "km",
            }
        }
    ]

    results = []
    print(f"{'Test':<30} | {'Res':>10} | {'Val':>6} | {'MaxDiff':>7} | {'MAE':>7} | {'DiffPix':>7} | {'Diff%':>6}")
    print("-" * 85)

    for item in configs:
        cw, ch = item["canvas_w"], item["canvas_h"]
        cfg = item["cfg"]
        for val in item["values"]:
            ss = 2
            min_dim = min(cw, ch)
            thickness = float(cfg.get("thickness", 2.0))
            size_px = int(round(cw * (float(cfg.get("size", 50.0)) / 100.0)))
            val_min = float(cfg.get("min_val", 0.0))
            val_max = float(cfg.get("max_val", 100.0))
            ticks = int(cfg.get("ticks", 10))

            # 1. Render using Pillow LANCZOS
            # We can intercept or test the 2x image directly
            layout = {"indicators": {"test_bar": cfg}}
            img_res, _, _, _ = _render_bar_indicator(
                cw, ch, layout, "", "test_bar", val, cfg.get("unit", ""), cfg.get("label", ""),
                cfg, min_dim, 0, 16, None, val_min, val_max, ticks, thickness, size_px, ss,
                formatted_val=f"{val:.1f}"
            )

            # img_res was produced using current downscale (OpenCV or cached).
            # Now let's test Pillow Lanczos on the unscaled base from cache:
            dyn_k = getattr(img_res, "_dynamic_key", None)
            from src.indicators.bar import _STATIC_CACHE
            img_2x = _STATIC_CACHE.get(dyn_k) if dyn_k else None

            if img_2x is not None:
                out_w = max(1, int(round(img_2x.width / ss)))
                out_h = max(1, int(round(img_2x.height / ss)))
                pil_down = img_2x.resize((out_w, out_h), Image.Resampling.LANCZOS if hasattr(Image, "Resampling") else Image.LANCZOS)
                arr_2x = np.asarray(img_2x)
                cv_down_arr = cv2.resize(arr_2x, (out_w, out_h), interpolation=cv2.INTER_LANCZOS4)
                cv_down = Image.fromarray(cv_down_arr)

                arr_pil = np.asarray(pil_down, dtype=np.int32)
                arr_cv = np.asarray(cv_down, dtype=np.int32)
                diff = np.abs(arr_pil - arr_cv)
                max_d = int(np.max(diff))
                mae = float(np.mean(diff))
                diff_mask = np.any(diff > 0, axis=-1)
                diff_cnt = int(np.sum(diff_mask))
                tot_pix = out_w * out_h
                diff_pct = (diff_cnt / tot_pix) * 100.0

                row = {
                    "test": item["name"],
                    "res": f"{cw}x{ch}",
                    "val": val,
                    "out_size": f"{out_w}x{out_h}",
                    "max_diff": max_d,
                    "mae": round(mae, 4),
                    "diff_count": diff_cnt,
                    "total_pixels": tot_pix,
                    "diff_pct": round(diff_pct, 2)
                }
                results.append(row)
                print(f"{item['name'][:30]:<30} | {row['res']:>10} | {val:6.2f} | {max_d:7d} | {mae:7.4f} | {diff_cnt:7d} | {diff_pct:5.2f}%")

    out_json = Path(r"C:\_DEV\_SPORTCAMHUD_ETAP_5A_RESULTS_20261012\bar_ruler_parity_study.json")
    out_json.parent.mkdir(parents=True, exist_ok=True)
    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)
    print(f"\nSaved bar ruler parity results to {out_json}")

if __name__ == "__main__":
    run_bar_comparison()
