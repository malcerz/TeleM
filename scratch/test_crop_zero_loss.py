import sys
from pathlib import Path
_root = Path(__file__).resolve().parent.parent
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

import numpy as np
from PIL import Image
from telemetry_fit import process_fit
from src.gui.layout_manager import normalize_layout
from src.indicators.compositor import compose_overlay
from src.ffmpeg.command_builder import get_layout_hud_bbox

layout = normalize_layout(None, 1920, 1080)
for k, v in layout["indicators"].items():
    if k not in ("speed_visual", "speed_text", "dist_visual", "dist_text", "alt_visual", "alt_text"):
        v["enabled"] = False

bx, by, bw, bh = get_layout_hud_bbox(layout, 1920, 1080)
print(f"Computed Bbox: x={bx} y={by} w={bw} h={bh}")

img_full = compose_overlay(
    1920, 1080, layout, "",
    "", "",
    25.0, 500.0, 5000.0,
    150.0, 50.0, 300.0,
    100.0, 500.0, 25.0,
    indicator_values={"speed_visual": 25.0, "speed_text": 25.0, "dist_visual": 500.0, "dist_text": 0.5, "alt_visual": 150.0, "alt_text": 150.0},
)

# 1. Direct crop
img_cropped = img_full.crop((bx, by, bx + bw, by + bh))

# 2. Re-embed cropped image at (bx, by) onto a blank 1920x1080 canvas
img_rebuilt = Image.new("RGBA", (1920, 1080), (0, 0, 0, 0))
img_rebuilt.paste(img_cropped, (bx, by))

arr_full = np.asarray(img_full)
arr_rebuilt = np.asarray(img_rebuilt)

diff = np.abs(arr_full.astype(np.int32) - arr_rebuilt.astype(np.int32))
max_diff = np.max(diff)
differing = np.count_nonzero(diff)

print(f"Direct Overlay Crop vs Full Comparison:")
print(f"  Max diff: {max_diff}")
print(f"  Differing pixels: {differing} (should be 0 - ZERO loss of pixels)")
print(f"  Clipping check: Any non-zero alpha outside bbox: {np.any(arr_full[:by, :, 3] > 0) or np.any(arr_full[by+bh:, :, 3] > 0) or np.any(arr_full[:, :bx, 3] > 0) or np.any(arr_full[:, bx+bw:, 3] > 0)}")
