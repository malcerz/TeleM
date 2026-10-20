"""Compare decoded 10-bit 4:2:0 code values of source and final (pre-display)."""
import sys, json
import numpy as np
W, H = 3840, 2160

def load(p):
    a = np.fromfile(p, dtype="<u2")
    y = a[:W*H].reshape(H, W).astype(np.float64)
    u = a[W*H:W*H + W*H//4].reshape(H//2, W//2).astype(np.float64)
    v = a[W*H + W*H//4:].reshape(H//2, W//2).astype(np.float64)
    return y, u, v

sy, su, sv = load(sys.argv[1]); fy, fu, fv = load(sys.argv[2])
res = {}
for name, tr in (("same", lambda a: a), ("rot180", lambda a: a[::-1, ::-1])):
    d = np.abs(tr(sy) - fy)
    res[name] = float(np.median(d))
orient = min(res, key=res.get)
tr = (lambda a: a) if orient == "same" else (lambda a: a[::-1, ::-1])
sy, su, sv = tr(sy), tr(su), tr(sv)
# HUD-free probe: per 64x64 block, keep blocks where |diff| median is small (HUD absent)
bs = 64
d = np.abs(sy - fy)
blk = d[:H//bs*bs, :W//bs*bs].reshape(H//bs, bs, W//bs, bs).mean(axis=(1, 3))
mask_blocks = blk < 12.0  # code-value units (10-bit); HUD blocks differ by hundreds
mask = np.zeros((H, W), dtype=bool)
mask[:H//bs*bs, :W//bs*bs] = np.kron(mask_blocks, np.ones((bs, bs))).astype(bool)
out = {
    "orientation_final_vs_source_raw": orient,
    "orientation_median_absdiff": res,
    "hud_free_fraction": float(mask.mean()),
    "src_Y_mean_all": float(sy.mean()), "fin_Y_mean_all": float(fy.mean()),
    "src_Y_mean_hudfree": float(sy[mask].mean()),
    "fin_Y_mean_hudfree": float(fy[mask].mean()),
    "Y_MAE_hudfree": float(d[mask].mean()), "Y_max_diff_hudfree": float(d[mask].max()),
    "Y_mean_signed_diff_hudfree(fin-src)": float((fy - sy)[mask].mean()),
    "src_Y_p01_p50_p99": [float(x) for x in np.percentile(sy[mask], [1, 50, 99])],
    "fin_Y_p01_p50_p99": [float(x) for x in np.percentile(fy[mask], [1, 50, 99])],
    "src_Y_min_max": [float(sy.min()), float(sy.max())],
    "fin_Y_min_max": [float(fy.min()), float(fy.max())],
    "U_mean_src_fin": [float(su.mean()), float(fu.mean())],
    "V_mean_src_fin": [float(sv.mean()), float(fv.mean())],
}
hist_s, edges = np.histogram(sy[mask], bins=16, range=(0, 1024))
hist_f, _ = np.histogram(fy[mask], bins=16, range=(0, 1024))
out["Y_hist16_src"] = hist_s.tolist(); out["Y_hist16_fin"] = hist_f.tolist()
print(json.dumps(out, indent=1))
