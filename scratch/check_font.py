import sys
from pathlib import Path
from PIL import Image, ImageDraw
root = Path("c:/_DEV/TeleM")
sys.path.insert(0, str(root))
from src.indicators.helpers import load_font

font_path = str(root / "assets/Roboto-Bold.ttf")

# Test various font sizes and what textbbox returns
for label_fs in [6, 10, 13, 19, 29, 59]:
    try:
        font = load_font(font_path, label_fs)
        img = Image.new("RGBA", (200, 200))
        draw = ImageDraw.Draw(img)
        bbox = draw.textbbox((0, 0), "100%", font=font)
        tw = bbox[2] - bbox[0]
        th = bbox[3] - bbox[1]
        print(f"label_fs={label_fs:3d}: textbbox(100%) = tw={tw}, th={th}")
    except Exception as e:
        print(f"label_fs={label_fs}: ERROR={e}")
