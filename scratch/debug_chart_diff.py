import sys
import json
from pathlib import Path
from datetime import timedelta

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.indicators.dispatcher import render_value_indicator
from src.indicators.chart import _render_chart_indicator
from src.indicators.chart_utils import generate_nice_time_ticks
from PIL import Image, ImageChops

with open("presets/cycling_dashboard_v10.json", "r", encoding="utf-8") as f:
    layout = json.load(f)

cfg1 = dict(layout["indicators"]["fit_heart_rate_text"])
cfg1["show_x_axis_values"] = True
cfg1["show_y_axis_values"] = True

cfg2 = dict(layout["indicators"]["fit_heart_rate_text"])
cfg2["show_x_axis_values"] = False
cfg2["show_y_axis_values"] = True

# Mock history data with timestamps
from datetime import datetime, timezone
base_dt = datetime(2026, 8, 22, 10, 0, 0, tzinfo=timezone.utc)
timestamps = [base_dt + timedelta(seconds=i) for i in range(600)]
class HistoryList(list):
    pass

history_values = HistoryList([140.0 + (i % 20) for i in range(600)])
history_values.timestamps = timestamps
history_values.chart_start_dt = timestamps[0]
history_values.chart_end_dt = timestamps[-1]
history_values.time_scope = "activity"

img1, x1, y1, _ = render_value_indicator(
    1280, 720, layout, "", "fit_heart_rate_text", 145.0, "bpm", "HEART RATE",
    cfg_override=cfg1, history_data=history_values, target_dt=timestamps[100],
)

img2, x2, y2, _ = render_value_indicator(
    1280, 720, layout, "", "fit_heart_rate_text", 145.0, "bpm", "HEART RATE",
    cfg_override=cfg2, history_data=history_values, target_dt=timestamps[100],
)

diff = ImageChops.difference(img1, img2)
bbox = diff.getbbox()
print(f"Direct render_value_indicator diff bbox: {bbox}")
if bbox:
    img1.crop(bbox).save("scratch/crop1.png")
    img2.crop(bbox).save("scratch/crop2.png")
