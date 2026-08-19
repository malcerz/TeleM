"""Compare Map Geometry across GUI Preview, CPU Reference, and AMD Native Final."""
import json
import sys
from pathlib import Path
from PIL import Image

root = Path("c:/_DEV/TeleM")
sys.path.insert(0, str(root))
sys.path.insert(0, str(root / "src"))

from src.gui.telemetry_manager import TelemetryDataManager
from src.telemetry_extract import (
    ensure_records_list, extract_altitude_samples, extract_exposure_samples,
    extract_iso_samples, extract_speed_samples, extract_temperature_samples,
    extract_track_samples, interpolate_value, load_json_with_fallback,
    smooth_speed_samples
)
from src.indicators.moving_map import render_map_working_image, _map_render_plan
from src.indicators.dispatcher import _render_moving_map_indicator
def s(val, base): return int(round(val * base / 100.0))

def compare_geometry():
    layout = json.load(open(root / "def_layout.json", encoding="utf-8"))
    cfg = layout["indicators"]["track_map"]
    
    print("=== CONFIG IN DEF_LAYOUT.JSON ===")
    print(f"x={cfg.get('x')}%, y={cfg.get('y')}%, size={cfg.get('size')}, zoom={cfg.get('zoom')}, style={cfg.get('map_style')}")
    
    # 1. GUI Preview Geometry (960x540)
    prev_w, prev_h = 960, 540
    prev_size_px = s(cfg.get("size", 10.0), prev_w) # in dispatcher: size_px = s(cfg.get('size', 10.0), canvas_w)
    prev_x = s(cfg["x"], prev_w)
    prev_y = s(cfg["y"], prev_h)
    prev_plan = _map_render_plan(prev_w, prev_size_px, int(cfg.get("zoom", 14)))
    prev_dst_bbox = (int(prev_x - prev_size_px // 2), int(prev_y - prev_size_px // 2), prev_size_px, prev_size_px)
    print(f"\n1. GUI PREVIEW (960x540):")
    print(f"  size_px={prev_size_px}")
    print(f"  center=({prev_x}, {prev_y})")
    print(f"  dst_bbox={prev_dst_bbox} (w={prev_dst_bbox[2]}, h={prev_dst_bbox[3]}, aspect={prev_dst_bbox[2]/prev_dst_bbox[3]:.2f})")
    print(f"  render_plan: {prev_plan}")

    # 2. CPU Reference (3840x2160)
    cpu_w, cpu_h = 3840, 2160
    cpu_size_px = s(cfg.get("size", 10.0), cpu_w)
    cpu_x = s(cfg["x"], cpu_w)
    cpu_y = s(cfg["y"], cpu_h)
    cpu_plan = _map_render_plan(cpu_w, cpu_size_px, int(cfg.get("zoom", 14)))
    cpu_dst_bbox = (int(cpu_x - cpu_size_px // 2), int(cpu_y - cpu_size_px // 2), cpu_size_px, cpu_size_px)
    print(f"\n2. CPU REFERENCE (3840x2160):")
    print(f"  size_px={cpu_size_px}")
    print(f"  center=({cpu_x}, {cpu_y})")
    print(f"  dst_bbox={cpu_dst_bbox} (w={cpu_dst_bbox[2]}, h={cpu_dst_bbox[3]}, aspect={cpu_dst_bbox[2]/cpu_dst_bbox[3]:.2f})")
    print(f"  render_plan: {cpu_plan}")

    # 3. AMD Native Map Blit (3840x2160)
    # Passed to native:
    # m_mapDstX = dst_bbox[0], m_mapDstY = dst_bbox[1]
    # m_mapSrcW = working_size (692), m_mapSrcH = working_size (692)
    # m_mapOutW = dst_bbox[2] (691), m_mapOutH = dst_bbox[3] (691)
    print(f"\n3. AMD NATIVE D3D11 PIPELINE:")
    print(f"  dstX={cpu_dst_bbox[0]}, dstY={cpu_dst_bbox[1]}")
    print(f"  srcW={cpu_plan['working_size']}, srcH={cpu_plan['working_size']}")
    print(f"  outW={cpu_dst_bbox[2]}, outH={cpu_dst_bbox[3]}")
    print(f"  Blit aspect ratio: {cpu_dst_bbox[2]} / {cpu_dst_bbox[3]} = {cpu_dst_bbox[2]/cpu_dst_bbox[3]:.2f}")

if __name__ == "__main__":
    compare_geometry()
