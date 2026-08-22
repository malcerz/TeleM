from PIL import Image, ImageDraw, ImageFont
import numpy as np
from pathlib import Path

fonts_to_test = {
    "default": None,
    "Comic Sans": r"C:\WINDOWS\Fonts\comic.ttf",
    "Digital-7": r"C:\Users\Malcerz\AppData\Local\Microsoft\Windows\Fonts\digital-7.ttf",
    "IONA-U1": r"C:\Users\Malcerz\AppData\Local\Microsoft\Windows\Fonts\IONA-U1.otf",
}

renders = {}

for label, fpath in fonts_to_test.items():
    img = Image.new("RGBA", (500, 140), (0, 0, 0, 255))
    d = ImageDraw.Draw(img)
    if fpath:
        fnt = ImageFont.truetype(fpath, size=48)
    else:
        fnt = ImageFont.load_default()

    d.text((20, 20), "1234567890", font=fnt, fill=(255, 255, 255, 255))
    d.text((20, 80), "SPEED 28.6", font=fnt, fill=(255, 255, 0, 255))

    out_p = Path(f"Raporty/FONT_TEST_{label.replace(' ', '_')}.png")
    img.save(out_p)
    arr = np.array(img)
    renders[label] = arr
    print(f"Rendered {label}: saved to {out_p}")

print("\n=== RASTER COMPARISONS ===")
for name in ["Comic Sans", "Digital-7", "IONA-U1"]:
    diff_default = np.abs(renders[name].astype(np.int16) - renders["default"].astype(np.int16)).max()
    print(f"Max pixel diff vs default for '{name}': {diff_default} (Different: {diff_default > 0})")

diff_dig_iona = np.abs(renders["Digital-7"].astype(np.int16) - renders["IONA-U1"].astype(np.int16)).max()
print(f"Max pixel diff Digital-7 vs IONA-U1: {diff_dig_iona} (Different: {diff_dig_iona > 0})")
