import json
import sys
from PIL import Image
import numpy as np

sys.path.insert(0, ".")
from src.indicators.helpers import s
from src.indicators.lean import _load_lean_rotation_source, get_lean_gpu_transform_info
from src.indicators.compositor import compose_overlay

layout = json.load(open("def_layout.json"))
lean_cfg = layout["indicators"]["lean_indicator"]
w, h = 3840, 2160
min_dim = 2160
outline_raw = int(layout.get("global", {}).get("text_outline", 3))
outline = max(0, int(round(outline_raw * min_dim / 1000)))
fs_val = lean_cfg.get("font_size") if "font_size" in lean_cfg else lean_cfg.get("size", 0.02)
fs = max(8, s(fs_val, min_dim))
size_px = s(lean_cfg.get("size", 0.1), w)

# Value on frame 150
value = 0.0

linfo = get_lean_gpu_transform_info(
    canvas_w=w, canvas_h=h, layout=layout, key="lean_indicator",
    value=value, cfg=lean_cfg, min_dim=min_dim, fs=fs,
    outline=outline, thickness=4, size_px=size_px, ss=1
)

ang, grp, px, py, spx, spy, dx, dy, tw, th = linfo
print(f"GPU Transform info: angle={ang}, pivot=({px},{py}), screen_pivot=({spx},{spy}), dst=({dx},{dy}), size=({tw},{th})")

# Render CPU full overlay
tm_bboxes = {}
tm_tight = {}
ref_canvas = Image.new("RGBA", (w, h), (0, 0, 0, 0))
img = compose_overlay(
    w, h, {"indicators": {"lean_indicator": lean_cfg}}, "arial.ttf",
    date_text="", time_text="", speed_value=0.0, distance_m=0.0,
    _bboxes=tm_bboxes, _tight_bboxes=tm_tight,
    extra_indicators={"lean_indicator": (value, "", "Lean")}
)

# Extract only the lean indicator bbox from ref_canvas:
bbox = tm_bboxes.get("lean_indicator")
print(f"CPU compose_overlay bbox: {bbox}")
print(f"CPU tight bbox: {tm_tight.get('lean_indicator')}")

# Save the CPU lean tile:
lean_tile = img.crop(bbox)
lean_tile.save("scratch/debug_lean_tile_full.png")
print("Saved debug_lean_tile_full.png")
