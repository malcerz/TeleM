"""Test map and HUD geometry scaling across 4K, 1080p, and 720p."""
import json
import sys
from pathlib import Path

root = Path("c:/_DEV/TeleM")
sys.path.insert(0, str(root))
sys.path.insert(0, str(root / "src"))

from src.indicators.moving_map import render_map_working_image, _map_render_plan
from src.indicators.helpers import s
from src.indicators.compositor import compose_overlay, _get_reusable_canvas

def test_map_scaling():
    layout = json.load(open(root / "def_layout.json", encoding="utf-8"))
    cfg = layout["indicators"]["track_map"]
    
    resolutions = [
        ("4k", 3840, 2160),
        ("1080p", 1920, 1080),
        ("720p", 1280, 720),
    ]
    
    print("=== MAP & HUD SCALING ACROSS RESOLUTIONS ===")
    for name, w, h in resolutions:
        map_w = s(cfg.get("size", 0.1), w)
        rx = s(cfg["x"], w)
        ry = s(cfg["y"], h)
        dst_bbox = (int(rx - map_w // 2), int(ry - map_w // 2), int(map_w), int(map_w))
        render_plan = _map_render_plan(w, map_w, int(cfg.get("zoom", 14)))
        
        print(f"\n--- RESOLUTION: {name} ({w}x{h}) ---")
        print(f"  Map center: ({rx}, {ry})")
        print(f"  Map width/height: {map_w}x{map_w} (size=18% of {w})")
        print(f"  Map dst_bbox: {dst_bbox} (aspect ratio = {dst_bbox[2]/dst_bbox[3]:.2f})")
        print(f"  Map working_size: {render_plan['working_size']}")
        print(f"  Map effective_zoom: {render_plan['effective_zoom']}")

if __name__ == "__main__":
    test_map_scaling()
