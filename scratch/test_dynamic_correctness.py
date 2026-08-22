import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import json
import numpy as np

from scratch.test_opt_time_display import render_time_display
from src.indicators.helpers import _STATIC_CACHE, resolve_indicator_font_path

with open("presets/cycling_dashboard_v10.json", "r", encoding="utf-8") as f:
    layout = json.load(f)

canvas_w, canvas_h = 1280, 720

base_img, _, _ = render_time_display(canvas_w, canvas_h, layout, "", "2026.08.14", "11:18:10", 10.0, 25.0)
base_arr = np.array(base_img)

# 1. Time change
img_time, _, _ = render_time_display(canvas_w, canvas_h, layout, "", "2026.08.14", "11:18:11", 10.0, 25.0)
diff_time = np.abs(base_arr.astype(np.int16) - np.array(img_time).astype(np.int16)).max()
print(f"Time change diff:      {diff_time} (Distinct: {diff_time > 0})")
assert diff_time > 0

# 2. Date change
img_date, _, _ = render_time_display(canvas_w, canvas_h, layout, "", "2026.08.15", "11:18:10", 10.0, 25.0)
diff_date = np.abs(base_arr.astype(np.int16) - np.array(img_date).astype(np.int16)).max()
print(f"Date change diff:      {diff_date} (Distinct: {diff_date > 0})")
assert diff_date > 0

# 3. Elapsed/Activity change
img_el, _, _ = render_time_display(canvas_w, canvas_h, layout, "", "2026.08.14", "11:18:10", 11.0, 25.0)
diff_el = np.abs(base_arr.astype(np.int16) - np.array(img_el).astype(np.int16)).max()
print(f"Elapsed change diff:   {diff_el} (Distinct: {diff_el > 0})")
assert diff_el > 0

# 4. Avg speed change
img_spd, _, _ = render_time_display(canvas_w, canvas_h, layout, "", "2026.08.14", "11:18:10", 10.0, 26.5)
diff_spd = np.abs(base_arr.astype(np.int16) - np.array(img_spd).astype(np.int16)).max()
print(f"Avg speed change diff: {diff_spd} (Distinct: {diff_spd > 0})")
assert diff_spd > 0

# 5. Font change
fpath_dig = resolve_indicator_font_path("Digital-7", "")
img_font, _, _ = render_time_display(canvas_w, canvas_h, layout, fpath_dig, "2026.08.14", "11:18:10", 10.0, 25.0)
assert img_font.size != base_img.size or not np.array_equal(np.array(img_font), base_arr)
print(f"Font change diff:      shape {img_font.size} vs {base_img.size} (Distinct: True)")

# 6. Toggle line off
layout_no_avg = json.loads(json.dumps(layout))
layout_no_avg["indicators"]["time_display"]["show_avg_speed"] = False
img_no_avg, _, _ = render_time_display(canvas_w, canvas_h, layout_no_avg, "", "2026.08.14", "11:18:10", 10.0, 25.0)
assert img_no_avg.height < base_img.height
print(f"Toggle avg speed off:  height reduced from {base_img.height} to {img_no_avg.height}")

print("\nALL DYNAMIC CORRECTNESS CHECKS PASSED!")
