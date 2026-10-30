"""CPU P0.4 Golden HUD analysis for GX010370 frame 1050 (export frame 150).

Separates three things:
  1. HUD DRAWING   editor HUD (render_preview) vs export-algorithm HUD vs the real
                   pre-compression export frame (RGBA, 8 bit), per HUD element.
  2. HLG MAPPING   lossless export frame vs an independent model of
                   base 10-bit frame + 8-bit HUD (BT.2020nc full range, HLG code
                   values, no transfer conversion).  No compression involved.
  3. COMPRESSION   Szybki/Zbalansowany/Jakość export frame vs the lossless one.

Usage: golden_analyze.py <golden_run_dir>   -> <dir>/golden_analysis.json
"""
import json
import subprocess
import sys
from pathlib import Path

import numpy as np
from PIL import Image

FF = r"C:\_DEV\SportCamHUD\runtime\common\ffmpeg\ffmpeg.exe"
VIDEO = r"D:\GoPro\GX010370.MP4"
W, H = 3840, 2160
START, IDX = 900, 150
ABS = START + IDX
S = 1.92  # 2000-px preview coordinates -> 3840

# Display (upright) coordinates in the 2000x1125 preview scale.
REGIONS = {
    "date_time_text": (50, 20, 260, 130),
    "map_and_gps_track": (22, 164, 323, 464),
    "distance_bar": (390, 55, 1610, 140),
    "battery_bar": (1700, 15, 1960, 105),
    "solar_bar": (1700, 140, 1960, 220),
    "compass": (1780, 260, 1960, 440),
    "lean_indicator": (1830, 520, 1940, 660),
    "gpmf_text_exp_iso_temp_bat": (15, 500, 135, 625),
    "altitude_scale": (25, 750, 95, 1100),
    "temperature_text": (1870, 755, 1995, 810),
    "speed_gauge": (820, 840, 1180, 1040),
    "power_bar": (740, 1040, 1260, 1120),
    "chart_cadence": (150, 900, 660, 1105),
    "chart_hr": (1330, 900, 1840, 1105),
}


def box(name, rotated=False):
    x0, y0, x1, y1 = (int(round(v * S)) // 2 * 2 for v in REGIONS[name])
    if rotated:  # stored (180-degree rotated) orientation
        x0, y0, x1, y1 = W - x1, H - y1, W - x0, H - y0
    return x0, y0, x1, y1


def load_rgba(path):
    return np.asarray(Image.open(path).convert("RGBA"))


def premul_zero(a):
    a = a.copy()
    a[a[..., 3] == 0] = 0
    return a


def diff_stats(a, b):
    d = np.abs(a.astype(np.int16) - b.astype(np.int16))
    px = (d.max(axis=-1) > 0)
    return {"max_diff": int(d.max()), "mae": round(float(d.mean()), 5), "different_pixels": int(px.sum()),
            "pixels": int(px.size)}


def decode_yuv(mp4, extra_in=(), select=True):
    cmd = [FF, "-v", "error", "-noautorotate", *extra_in, "-i", mp4]
    if select:
        cmd += ["-vf", f"select=eq(n\\,{IDX})"]
    cmd += ["-frames:v", "1", "-pix_fmt", "yuv420p10le", "-f", "rawvideo", "-"]
    raw = subprocess.run(cmd, capture_output=True).stdout
    a = np.frombuffer(raw, dtype="<u2")
    y = a[:W * H].reshape(H, W).astype(np.int32)
    u = a[W * H:W * H + W * H // 4].reshape(H // 2, W // 2).astype(np.int32)
    v = a[W * H + W * H // 4:].reshape(H // 2, W // 2).astype(np.int32)
    return y, u, v


def psnr(a, b, peak=1023.0):
    mse = float(np.mean((a.astype(np.float64) - b.astype(np.float64)) ** 2))
    return 99.0 if mse == 0 else round(10 * np.log10(peak * peak / mse), 3)


def main():
    d = Path(sys.argv[1])
    out = {}
    e1 = premul_zero(load_rgba(d / f"editor_hud_f{ABS}.png"))
    e2 = premul_zero(load_rgba(d / f"exportalgo_hud_f{ABS}.png"))
    xs = {}
    for tag, p in (("LOSSLESS", d / f"export_hud_f{IDX}.rgba"), ("fast", d / "fast" / f"export_hud_f{IDX}.rgba"),
                   ("balanced", d / "balanced" / f"export_hud_f{IDX}.rgba"),
                   ("quality", d / "quality" / f"export_hud_f{IDX}.rgba")):
        if p.exists():
            xs[tag] = np.fromfile(p, dtype=np.uint8).reshape(H, W, 4)
    x = premul_zero(xs["LOSSLESS"])
    x_up = x[::-1, ::-1]  # export HUD is stored rotated 180 deg (display matrix restores it)

    # ---- 1. drawing -------------------------------------------------------
    draw = {"editor_vs_exportalgo": diff_stats(e1, e2), "exportalgo_vs_export_precompression": diff_stats(e2, x_up),
            "editor_vs_export_precompression": diff_stats(e1, x_up), "per_element": {}}
    for name in REGIONS:
        x0, y0, x1, y1 = box(name)
        draw["per_element"][name] = {
            "editor_vs_exportalgo": diff_stats(e1[y0:y1, x0:x1], e2[y0:y1, x0:x1]),
            "exportalgo_vs_export": diff_stats(e2[y0:y1, x0:x1], x_up[y0:y1, x0:x1]),
            "hud_coverage_pct": round(100.0 * float((x_up[y0:y1, x0:x1, 3] > 0).mean()), 1)}
    draw["determinism_precompression_across_runs"] = {
        t: diff_stats(x, premul_zero(v)) for t, v in xs.items() if t != "LOSSLESS"}
    out["1_hud_drawing"] = draw

    # ---- 2. HLG mapping (lossless export, no compression) ----------------
    src = f"{d}/LOSSLESS.mp4"
    yo, uo, vo = decode_yuv(src)
    yb, ub, vb = decode_yuv(VIDEO, extra_in=("-ss", f"{START * 1001 / 30000:.9f}"))
    A = x[..., 3].astype(np.float64)
    rgb = x[..., :3].astype(np.float64) / 255.0
    Kr, Kb = 0.2627, 0.0593
    Kg = 1 - Kr - Kb
    Yh = Kr * rgb[..., 0] + Kg * rgb[..., 1] + Kb * rgb[..., 2]
    Cb = (rgb[..., 2] - Yh) / (2 * (1 - Kb))
    Cr = (rgb[..., 0] - Yh) / (2 * (1 - Kr))
    Yh10 = np.rint(Yh * 1023)
    Cb10 = np.rint(Cb * 1023 + 512)
    Cr10 = np.rint(Cr * 1023 + 512)
    mp = {}
    opaque = A == 255
    dy = np.abs(yo[opaque] - Yh10[opaque])
    mp["opaque_luma"] = {"pixels": int(opaque.sum()), "max_abs_code_diff": int(dy.max()),
                         "mae_codes": round(float(dy.mean()), 4), "within_2_codes_pct": round(100 * float((dy <= 2).mean()), 3)}
    # chroma on 2x2 blocks that are fully opaque and a single colour
    blk = opaque.reshape(H // 2, 2, W // 2, 2)
    full = blk.all(axis=(1, 3))
    cb_b = Cb10.reshape(H // 2, 2, W // 2, 2)
    cr_b = Cr10.reshape(H // 2, 2, W // 2, 2)
    uni = full & (cb_b.max(axis=(1, 3)) == cb_b.min(axis=(1, 3))) & (cr_b.max(axis=(1, 3)) == cr_b.min(axis=(1, 3)))
    dcb = np.abs(uo[uni] - cb_b[:, 0, :, 0][uni])
    dcr = np.abs(vo[uni] - cr_b[:, 0, :, 0][uni])
    mp["opaque_uniform_chroma"] = {"blocks": int(uni.sum()), "cb_max": int(dcb.max()) if dcb.size else None,
                                   "cb_mae": round(float(dcb.mean()), 4) if dcb.size else None,
                                   "cr_max": int(dcr.max()) if dcr.size else None,
                                   "cr_mae": round(float(dcr.mean()), 4) if dcr.size else None}
    semi = (A > 0) & (A < 255)
    exp_semi = yb[semi] + (Yh10[semi] - yb[semi]) * A[semi] / 255.0
    ds = np.abs(yo[semi] - exp_semi)
    mp["semi_transparent_luma"] = {"pixels": int(semi.sum()), "max_abs_code_diff": round(float(ds.max()), 2),
                                   "mae_codes": round(float(ds.mean()), 4),
                                   "within_3_codes_pct": round(100 * float((ds <= 3).mean()), 3)}
    zero_blocks = (A == 0).reshape(H // 2, 2, W // 2, 2).all(axis=(1, 3))
    zy = (A == 0)
    mp["transparent_pixels_equal_base"] = {
        "luma_diff_pixels": int((yo[zy] != yb[zy]).sum()), "luma_pixels": int(zy.sum()),
        "chroma_diff_blocks": int(((uo != ub) | (vo != vb))[zero_blocks].sum()), "chroma_blocks": int(zero_blocks.sum())}
    out["2_hlg_mapping_lossless"] = mp

    # ---- 3. compression loss --------------------------------------------
    comp = {}
    for prof in ("fast", "balanced", "quality"):
        mp4 = d / f"P_{prof}.mp4"
        if not mp4.exists():
            continue
        yc, uc, vc = decode_yuv(str(mp4))
        r = {"overall": {"psnr_y": psnr(yc, yo), "psnr_u": psnr(uc, uo), "psnr_v": psnr(vc, vo)}, "regions_psnr_y": {}}
        for name in REGIONS:
            x0, y0, x1, y1 = box(name, rotated=True)
            r["regions_psnr_y"][name] = psnr(yc[y0:y1, x0:x1], yo[y0:y1, x0:x1])
        comp[prof] = r
    out["3_compression_vs_lossless_frame150"] = comp
    json.dump(out, open(d / "golden_analysis.json", "w"), indent=1)
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
