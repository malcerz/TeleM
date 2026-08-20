import sys
from pathlib import Path
_root = Path(__file__).resolve().parent.parent
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

from src.gui.layout_manager import normalize_layout
from src.indicators.compositor import compose_overlay
import numpy as np
from PIL import Image

layout = normalize_layout("def_layout.json", 1920, 1080)

# Render a sample frame to see exact alpha positions of indicators
img = compose_overlay(
    1920, 1080, layout, "",
    "2026-08-20", "12:34:56",
    28.5, 4500.0, 12000.0,
    145.0, 50.0, 300.0,
    100.0, 500.0, 25.0,
    indicator_values={
        "fit_cadence_text": 85.0,
        "fit_enhanced_speed_text": 28.5,
        "fit_heart_rate_text": 142.0,
        "fit_temperature_text": 24.5,
        "iso_text": 100.0,
        "exposure_text": 500.0,
        "temp_text": 25.0,
        "fit_battery_text": 85.0,
        "fit_battery_pct_text": 85.0,
        "fit_solar_pct_text": 45.0,
    },
    chart_data={"cadence": [(i, 70 + i%30) for i in range(100)], "heart_rate": [(i, 130 + i%20) for i in range(100)]},
    gps_track=[(52.0 + i*0.001, 21.0 + i*0.001) for i in range(100)],
    current_position=0.5,
)

arr = np.asarray(img)
alpha = arr[..., 3]

print("Canvas shape:", arr.shape)
y_idx, x_idx = np.nonzero(alpha > 0)
print(f"Overall alpha bounds: X=[{np.min(x_idx)}, {np.max(x_idx)}] Y=[{np.min(y_idx)}, {np.max(y_idx)}]")

# Look at distinct clusters in Y:
# Top cluster: time_block (y ~ 20..150)
# Middle-left cluster: camera settings (iso, exp, temp: y ~ 400..600, x ~ 20..200)
# Middle-right cluster: map + temp/batt (y ~ 200..500, x ~ 1600..1900)
# Bottom cluster: charts + gauge (y ~ 750..1060, x ~ 300..1800)
