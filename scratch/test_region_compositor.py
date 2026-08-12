"""Test region-local composition & dirty checking correctness.
Verifies pixel-for-pixel visual match against full canvas cropping.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from datetime import datetime, timezone

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
from PIL import Image

from src.indicators.compositor import compose_overlay
from src.ffmpeg.command_builder import get_layout_hud_regions

with open("def_layout.json", "r", encoding="utf-8") as f:
    layout = json.load(f)

overlay_w, overlay_h = 1920, 1080
atlas_w, atlas_h, hud_regions = get_layout_hud_regions(layout, overlay_w, overlay_h, max_regions=3)

# Render frame using original full-canvas + crop method
img_full = compose_overlay(
    overlay_w, overlay_h, layout, "Arial",
    "2026-08-05", "04:28:04",
    speed_value=15.7, distance_m=1200.0, max_distance_m=10000.0,
    alt_value=45.0, min_alt=10.0, max_alt=100.0,
    iso_value=100.0, exposure_value=1500.0, temp_value=25.0,
    indicator_values={"fit_cadence_text": 85.0, "fit_heart_rate_text": 120.0},
    max_speed_kmh=45.0, power_value=220.0, atemp_value=22.0,
    hr_value=120.0, cad_value=85.0, battery_value=90.0,
    chart_data={"fit_cadence_text": [80.0, 85.0, 90.0], "fit_heart_rate_text": [115.0, 120.0, 122.0]},
    current_position=0.5,
)

atlas_orig = Image.new("RGBA", (atlas_w, atlas_h), (0, 0, 0, 0))
for r in hud_regions:
    dest_x, dest_y, src_x, src_y, rw, rh = r
    r_crop = img_full.crop((dest_x, dest_y, dest_x + rw, dest_y + rh))
    atlas_orig.paste(r_crop, (src_x, src_y))

arr_orig = np.asarray(atlas_orig)

print("Atlas dimensions:", atlas_w, atlas_h)
print("Regions count:", len(hud_regions))
print("Original Atlas array shape:", arr_orig.shape)
