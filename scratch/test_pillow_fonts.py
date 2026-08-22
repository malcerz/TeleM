from PIL import ImageFont, Image, ImageDraw
from pathlib import Path

files = {
    "Comic Sans": r"C:\WINDOWS\Fonts\comic.ttf",
    "Digital-7": r"C:\Users\Malcerz\AppData\Local\Microsoft\Windows\Fonts\digital-7.ttf",
    "Digital-7 Mono": r"C:\Users\Malcerz\AppData\Local\Microsoft\Windows\Fonts\digital-7 (mono).ttf",
    "IONA-U1": r"C:\Users\Malcerz\AppData\Local\Microsoft\Windows\Fonts\IONA-U1.otf",
}

for name, path_str in files.items():
    p = Path(path_str)
    print(f"\n--- Testing {name} ---")
    print(f"Path: {p} (exists={p.is_file()}, suffix={p.suffix})")
    try:
        fnt = ImageFont.truetype(str(p), size=48)
        print(f"Pillow truetype load: SUCCESS -> {fnt.getname()}")
        # Test rendering text
        img = Image.new("RGBA", (400, 100), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        d.text((10, 10), "1234567890 SPEED 28.6", font=fnt, fill=(255, 255, 255, 255))
        non_zero = sum(1 for px in img.getdata() if px[3] > 0)
        print(f"Render text test: SUCCESS ({non_zero} non-zero pixels)")
    except Exception as e:
        print(f"Pillow truetype load: FAILED ({e})")
