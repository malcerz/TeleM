import json
import os
import sys
from pathlib import Path

repo_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(repo_root))

from PIL import Image
import numpy as np

from src.gui.telemetry_manager import TelemetryDataManager
from src.telemetry_processed_cache import read_processed_cache, apply_processed_cache
from src.indicators.compositor import compose_overlay
from src.indicators.dispatcher import render_value_indicator
from src.indicators.rotated_paste import rotated_paste
from src.ffmpeg.amd_native_exporter import _ordered_map_layout_parts

layout = json.load(open(repo_root / "def_layout.json", encoding="utf-8"))
w, h = 3840, 2160
font_path = "arial.ttf"

compose_layout, map_above_layout, map_after_keys = _ordered_map_layout_parts(layout)
if "indicators" in map_above_layout and "lean_indicator" in map_above_layout["indicators"]:
    map_above_layout["indicators"]["lean_indicator"]["enabled"] = False

gpu_chart_keys = {"fit_cadence_text", "fit_heart_rate_text"}
gpu_gauge_key = "speed_text"
above_capture_keys = gpu_chart_keys | {gpu_gauge_key}

above_bboxes_ref = {}
above_tight_bboxes_ref = {}

gt_canvas = compose_overlay(
    canvas_w=w, canvas_h=h, layout=map_above_layout, font_path=font_path,
    date_text="2026-08-26", time_text="12:00:00",
    speed_value=25.0, distance_m=0.0,
    alt_value=250.0, temp_value=22.0, iso_value=100, exposure_value=240.0,
    _bboxes=above_bboxes_ref, _tight_bboxes=above_tight_bboxes_ref,
    gpu_capture_keys=above_capture_keys, gpu_capture={}, reuse_canvas="above",
)

# Test 1: Only distance
t_dist = Image.new("RGBA", (w, h), (0, 0, 0, 0))
dist_cfg = map_above_layout["indicators"]["fit_distance_text"]
dist_res, dist_rx, dist_ry, _ = render_value_indicator(
    canvas_w=w, canvas_h=h, layout=map_above_layout, font_path=font_path,
    key="fit_distance_text", value=0.0,
    unit=dist_cfg.get("unit", "km"), label=dist_cfg.get("title", ""),
)
rotated_paste(t_dist, dist_res, dist_rx, dist_ry, 0)
gt_dist_crop = gt_canvas.crop((dist_rx - dist_res.width//2, dist_ry - dist_res.height//2, dist_rx + dist_res.width//2, dist_ry + dist_res.height//2))
t_dist_crop = t_dist.crop((dist_rx - dist_res.width//2, dist_ry - dist_res.height//2, dist_rx + dist_res.width//2, dist_ry + dist_res.height//2))
diff_dist = np.abs(np.asarray(gt_dist_crop).astype(np.int32) - np.asarray(t_dist_crop).astype(np.int32))
print("Distance Diff:", np.max(diff_dist), "Diff pixels:", np.sum(diff_dist > 0) // 4)

# Print where GT canvas differs from blank for distance
gt_arr = np.asarray(gt_canvas)
print("GT bboxes:", above_bboxes_ref)
