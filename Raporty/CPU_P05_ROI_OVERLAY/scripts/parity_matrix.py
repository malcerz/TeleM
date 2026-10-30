"""CPU P0.5: bit-exact pre-compression parity, full-frame overlay vs ROI/atlas overlay.

For each layout x timestamp x plan (and the HUD flipped 180 deg = other source orientation)
run the FFmpeg overlay stage to raw yuv420p10le (no encoder) on the real 4K HLG base and compare
every Y/U/V sample.  Also reports alpha>0 pixels not covered by the plan (must be 0).
"""
import json, os, subprocess, sys
import numpy as np
sys.path.insert(0, "C:/_DEV/SportCamHUD/Raporty/CPU_P05_ROI_OVERLAY/prototype")
import cpu_hud_roi as roi

FF = r"C:\_DEV\SportCamHUD\runtime\common\ffmpeg\ffmpeg.exe"
VIDEO = r"D:\GoPro\GX010370.MP4"
ROOT = "C:/_DEV/SportCamHUD/Raporty/CPU_P05_ROI_OVERLAY"
W, H = 3840, 2160
FULL = "[0:v]null[base];[1:v]setpts=PTS-STARTPTS[ov];[base][ov]overlay=0:0:shortest=1:format=yuv420p10[v]"
FRAMES = (0, 80, 160, 240, 319)
NF = 2


def run(cmd):
    r = subprocess.run(cmd, capture_output=True)
    if r.returncode:
        raise RuntimeError(r.stderr.decode(errors="replace")[-400:])


def base_cmd():
    return [FF, "-y", "-v", "error", "-noautorotate", "-ss", f"{900 * 1001 / 30000:.9f}", "-i", VIDEO]


def main():
    os.makedirs(ROOT + "/proto", exist_ok=True)
    out = {}
    plans_cfg = {"min_area(tile16,ov60k)": dict(tile=16, margin_px=16, overhead_px=60_000, max_regions=24),
                 "cost_opt(tile16,ov1400k)": dict(tile=16, margin_px=16, overhead_px=1_400_000, max_regions=24),
                 "tile64(ov60k)": dict(tile=64, margin_px=16, overhead_px=60_000, max_regions=24)}
    for layout in ("def", "v10", "v3"):
        frames = {f: np.fromfile(f"{ROOT}/frames/{layout}/export_hud_f{f}.rgba", dtype=np.uint8).reshape(H, W, 4)
                  for f in FRAMES}
        for orient in ("stored_rot180", "flipped_0deg"):
            fr = {f: (a if orient == "stored_rot180" else np.ascontiguousarray(a[::-1, ::-1])) for f, a in frames.items()}
            union = roi.alpha_union(a[..., 3] for a in fr.values())
            for pname, cfg in plans_cfg.items():
                plan = roi.plan_from_mask(union, **cfg)
                for f in FRAMES:
                    full_path = f"{ROOT}/proto/pm_full.rgba"
                    fr[f].tofile(full_path)
                    atlas = np.zeros((plan.atlas_h, plan.atlas_w, 4), dtype=np.uint8)
                    roi.pack_into_atlas(plan, fr[f], atlas)
                    apath = f"{ROOT}/proto/pm_atlas.rgba"
                    atlas.tofile(apath)
                    ya, yb = f"{ROOT}/proto/pm_a.yuv", f"{ROOT}/proto/pm_b.yuv"
                    run(base_cmd() + ["-stream_loop", "-1", "-f", "rawvideo", "-pix_fmt", "rgba", "-s", f"{W}x{H}",
                                      "-framerate", "30000/1001", "-i", full_path, "-filter_complex", FULL,
                                      "-map", "[v]", "-frames:v", str(NF), "-pix_fmt", "yuv420p10le", "-f", "rawvideo", ya])
                    g = "[0:v]null[base];" + roi.build_roi_filter(plan, convert_atlas_once=True)
                    run(base_cmd() + ["-stream_loop", "-1", "-f", "rawvideo", "-pix_fmt", "rgba", "-s",
                                      f"{plan.atlas_w}x{plan.atlas_h}", "-framerate", "30000/1001", "-i", apath,
                                      "-filter_complex", g, "-map", "[vtemp]", "-frames:v", str(NF),
                                      "-pix_fmt", "yuv420p10le", "-f", "rawvideo", yb])
                    A = np.fromfile(ya, dtype="<u2").astype(np.int32)
                    B = np.fromfile(yb, dtype="<u2").astype(np.int32)
                    d = np.abs(A - B)
                    key = f"{layout}|{orient}|{pname}|f{f}"
                    out[key] = {"regions": len(plan.cells), "region_pct": round(100 * plan.fraction_of_canvas, 2),
                                "atlas_pct": round(100 * plan.atlas_fraction, 2),
                                "uncovered_alpha_px": roi.uncovered_alpha_pixels(plan, fr[f][..., 3]),
                                "max_diff": int(d.max()), "different_samples": int((d > 0).sum()),
                                "samples": int(d.size)}
                    print(key, out[key], flush=True)
    json.dump(out, open(ROOT + "/analysis/parity_matrix.json", "w"), indent=1)
    bad = [k for k, v in out.items() if v["max_diff"] or v["uncovered_alpha_px"]]
    print("TOTAL", len(out), "cases; non-exact:", len(bad), bad[:5])


if __name__ == "__main__":
    main()
