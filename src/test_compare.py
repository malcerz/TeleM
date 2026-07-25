import sys
sys.path.append('e:/GoPro/TeleM/TeleMGP/src')
from overlay_renderer import render_value_indicator

layout = {
    "global": {"text_outline": 3, "antialiasing": 4},
    "indicators": {
        "speed_visual": {
            "form": "gauge",
            "size": 0.2,
            "thickness": 5,
            "min_val": 0,
            "max_val": 60,
            "font_size": 0.04,
            "x": 0.5,
            "y": 0.5,
            "label": "Speed",
        }
    },
}

font_path = r"C:/Windows/Fonts/arial.ttf"

# ss=1 (no AA)
img1, _, _, _ = render_value_indicator(400, 400, layout, font_path, "speed_visual", 23, "km/h", "Speed", supersample=1)
img1.save(r"e:/GoPro/TeleM/TeleMGP/src/gauge_ss1.png")

# ss=4 (with AA)
img4, _, _, _ = render_value_indicator(400, 400, layout, font_path, "speed_visual", 23, "km/h", "Speed", supersample=4)
img4.save(r"e:/GoPro/TeleM/TeleMGP/src/gauge_ss4.png")

print("Saved gauge_ss1.png and gauge_ss4.png")
