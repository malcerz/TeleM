import sys
import os
# Ensure src directory is on path
sys.path.append('e:/GoPro/TeleM/TeleMGP/src')
from overlay_renderer import render_value_indicator

# Minimal layout configuration for a gauge indicator
layout = {
    "global": {"text_outline": 3},
    "indicators": {
        "speed_visual": {
            "form": "gauge",
            "size": 0.2,
            "thickness": 5,
            "min_val": 0,
            "max_val": 200,
            "x": 0.5,
            "y": 0.5,
            "label": "Speed"
        }
    }
}

font_path = r"C:/Windows/Fonts/arial.ttf"
# Render with supersampling factor 2
img, x, y, _ = render_value_indicator(
    canvas_w=400,
    canvas_h=400,
    layout=layout,
    font_path=font_path,
    key="speed_visual",
    value=120,
    unit="km/h",
    label="Speed",
    supersample=2,
)
# Save the resulting image for visual inspection
output_path = r"e:/GoPro/TeleM/TeleMGP/src/test_gauge.png"
img.save(output_path)
print("Saved", output_path)
