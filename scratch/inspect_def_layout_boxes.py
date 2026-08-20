import sys
from pathlib import Path
_root = Path(__file__).resolve().parent.parent
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

import json
from src.gui.layout_manager import normalize_layout
from src.ffmpeg.command_builder import get_layout_hud_regions, get_layout_hud_bbox

layout = normalize_layout('def_layout.json', 1920, 1080)
for k, v in layout.get('indicators', {}).items():
    if v.get('enabled', True):
        print(f"{k:30s} | x={v.get('x'):.1f} y={v.get('y'):.1f} form={v.get('form')}")

aw, ah, regs = get_layout_hud_regions(layout, 1920, 1080, max_regions=3)
print(f"\nAtlas size: {aw}x{ah} -> {aw*ah/(1920*1080)*100:.1f}%")
for i, r in enumerate(regs):
    print(f"  Region {i}: {r}")
