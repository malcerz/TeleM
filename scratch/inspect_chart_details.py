import time
import json
from pathlib import Path
import src.indicators.chart as chart
import src.indicators.chart_utils as chart_utils

root = Path(__file__).resolve().parents[1]
layout_path = root / "presets" / "cycling_dashboard_v10.json"
with open(layout_path, "r", encoding="utf-8") as f:
    layout = json.load(f)

print("Chart Cache Stats:")
print("  Average layer stats:", chart_utils.get_average_layer_cache_stats())
