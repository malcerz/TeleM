"""
Multi-resolution and dynamic map size test.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(".").resolve()))

from src.indicators.moving_map import _map_render_plan

resolutions = [
    (3840, 2160, "4K"),
    (1920, 1080, "1080p"),
    (1280, 720, "720p"),
    (854, 480, "480p"),
]

map_sizes = [
    (0.12, "Small"),
    (0.18, "Medium (Default)"),
    (0.25, "Large"),
]

print("=== MULTI-RESOLUTION & DYNAMIC MAP SIZE AUDIT ===")
print("Res     | Size Name        | Config Size | Desired px | Actual px | Working px | Output Scale | Selected GPU Path")
print("--------+------------------+-------------+------------+-----------+------------+--------------+------------------")

for w, h, res_name in resolutions:
    for cfg_size, size_name in map_sizes:
        desired_px = int(round(w * cfg_size))
        plan = _map_render_plan(w, desired_px, 16)
        actual_px = plan["working_size"]
        out_px = plan["output_size"]
        scale = plan["output_resize_scale"]
        path_selected = "DIRECT_1TO1" if abs(scale - 1.0) < 1e-6 else "REFERENCE_RESAMPLE"
        print(f"{res_name:<7} | {size_name:<16} | {cfg_size:<11.2f} | {desired_px:<10} | {actual_px:<9} | {out_px:<10} | {scale:<12.4f} | {path_selected}")
