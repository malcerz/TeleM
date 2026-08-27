# ETAP 2A: tight zoom crops of the residual strip (ref vs cand).
import os

from PIL import Image

BASE = r"c:\_DEV\TeleM\scratch\etap2a_test"
BOX = (1360, 1530, 1840, 1670)  # tight around strip
SCALE = 6


def render(src_path, out_path):
    im = Image.open(src_path).convert("RGBA").crop(BOX)
    # composite over mid-gray checkerboard-ish background to reveal alpha
    bg = Image.new("RGBA", im.size, (40, 90, 40, 255))
    bg.alpha_composite(im)
    rgb = bg.convert("RGB")
    # alpha heat map
    a = im.getchannel("A").convert("RGB")
    w, h = rgb.size
    canvas = Image.new("RGB", (w * 2 + 12, h), (20, 20, 20))
    canvas.paste(rgb, (0, 0))
    canvas.paste(a, (w + 12, 0))
    canvas = canvas.resize(
        ((w * 2 + 12) * SCALE, h * SCALE), Image.NEAREST,
    )
    canvas.save(out_path)
    print("saved", out_path)


render(os.path.join(BASE, "ref_short_H_hud_canvas_30.png"), os.path.join(BASE, "zoom_ref_f30.png"))
render(os.path.join(BASE, "cand_short_H_hud_canvas_30.png"), os.path.join(BASE, "zoom_cand_f30.png"))
