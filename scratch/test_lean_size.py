import json
import sys
sys.path.insert(0, ".")
from src.indicators.helpers import s
from src.indicators.lean import _load_lean_rotation_source, get_lean_gpu_transform_info

layout = json.load(open("def_layout.json"))
lean_cfg = layout["indicators"]["lean_indicator"]

w, h = 3840, 2160
size_val = lean_cfg.get("size", 8.0)
size_px_correct = s(size_val, w)
print(f"Config size: {size_val}, Correct size_px for 4K: {size_px_correct}")

rot_src = _load_lean_rotation_source(lean_cfg, size_px_correct)
print(f"Loaded sprite with correct size: {rot_src.gw}x{rot_src.gh}, pivot={rot_src.pivot_px},{rot_src.pivot_py}")
rot_src.graphic.save("scratch/debug_correct_lean_sprite.png")

linfo = get_lean_gpu_transform_info(
    canvas_w=w,
    canvas_h=h,
    layout=layout,
    key="lean_indicator",
    value=15.0,
    cfg=lean_cfg,
    min_dim=2160,
    fs=max(8, s(lean_cfg.get("font_size", 2.5), 2160)),
    outline=max(0, int(round(3 * 2160 / 1000))),
    thickness=4,
    size_px=size_px_correct,
    ss=1
)
print(f"Transform info with correct size: {linfo}")
