"""Luma statistics of display renderings (8-bit RGB) on HUD-free video blocks."""
import json, sys
import numpy as np
from PIL import Image
Image.MAX_IMAGE_PIXELS = None
W, H, BS = 3840, 2160, 64
tmp, scene, src_yuv, fin_yuv = sys.argv[1:5]

def y10(p):
    return np.fromfile(p, dtype="<u2")[:W*H].reshape(H, W).astype(np.float64)
sy = y10(src_yuv)[::-1, ::-1]; fy = y10(fin_yuv)
d = np.abs(sy - fy)
blk = d[:H//BS*BS, :W//BS*BS].reshape(H//BS, BS, W//BS, BS).mean(axis=(1, 3)) < 12.0
mask = np.zeros((H, W), bool); mask[:H//BS*BS, :W//BS*BS] = np.kron(blk, np.ones((BS, BS))).astype(bool)

def luma(name):
    im = Image.open(f"{tmp}/{name}_{scene}.png").convert("RGB")
    if im.size != (W, H):
        im = im.resize((W, H), Image.BOX)
    a = np.asarray(im, dtype=np.float64)
    return 0.2126*a[..., 0] + 0.7152*a[..., 1] + 0.0722*a[..., 2]

ref = luma("mpv_src")
res = {"scene": scene, "hud_free_fraction": float(mask.mean()), "renderings": {}}
labels = {
    "mpv_src": "Preview: libmpv + SportCamHUD options, SOURCE MP4",
    "mpv_fin": "Preview options (libmpv) applied to FINAL MP4",
    "plA": "libplacebo bt.2390, no peak detect (= preview settings), FINAL",
    "plB": "libplacebo defaults (= stock mpv/libplacebo player), FINAL",
    "plC": "FINAL misread as LIMITED range, then preview tonemap",
    "plD": "FINAL without HLG tone mapping (HLG code values shown as SDR)",
}
for k, lab in labels.items():
    L = luma(k)
    dd = np.abs(L - ref)[mask]
    res["renderings"][k] = {
        "label": lab,
        "mean_luma_8bit_hudfree": round(float(L[mask].mean()), 2),
        "p10_p50_p90": [round(float(x), 1) for x in np.percentile(L[mask], [10, 50, 90])],
        "vs_preview_source_MAE": round(float(dd.mean()), 3),
        "vs_preview_source_max_diff": round(float(dd.max()), 1),
        "vs_preview_source_diff_pixels_gt2": int((dd > 2).sum()),
    }
print(json.dumps(res, indent=1))
