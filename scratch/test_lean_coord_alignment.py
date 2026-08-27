import json
import sys
sys.path.insert(0, ".")
from src.indicators.helpers import s
from src.indicators.lean import _load_lean_rotation_source, get_lean_gpu_transform_info

layout = json.load(open("def_layout.json"))
lean_cfg = layout["indicators"]["lean_indicator"]
w, h = 3840, 2160
min_dim = 2160
outline_raw = int(layout.get("global", {}).get("text_outline", 3))
outline = max(0, int(round(outline_raw * min_dim / 1000)))
fs_val = lean_cfg.get("font_size") if "font_size" in lean_cfg else lean_cfg.get("size", 0.02)
fs = max(8, s(fs_val, min_dim))
size_px = s(lean_cfg.get("size", 0.1), w)

linfo = get_lean_gpu_transform_info(
    canvas_w=w,
    canvas_h=h,
    layout=layout,
    key="lean_indicator",
    value=0.0,
    cfg=lean_cfg,
    min_dim=min_dim,
    fs=fs,
    outline=outline,
    thickness=4,
    size_px=size_px,
    ss=1
)
print("Current get_lean_gpu_transform_info dst:", linfo[6], linfo[7], linfo[8], linfo[9])

# What was the expected bbox from compose_overlay?
from src.indicators.compositor import compose_overlay
from src.indicators.frame_data import prepare_overlay_frame_data
tm_bboxes = {}
tm_tight = {}
img = compose_overlay(
    w, h, {"indicators": {"lean_indicator": lean_cfg}}, "arial.ttf",
    date_text="", time_text="", speed_value=0.0, distance_m=0.0,
    _bboxes=tm_bboxes, _tight_bboxes=tm_tight,
    extra_indicators={"lean_indicator": (0.0, "", "Lean")}
)
print("compose_overlay lean bbox:", tm_bboxes.get("lean_indicator"))
print("compose_overlay lean tight:", tm_tight.get("lean_indicator"))
