"""CPU P0.5 stage 1: occupancy analysis and ROI plans from real HUD frames.

For each layout (3) and tile size / margin variants:
  * true alpha>0 coverage per frame and union over frames,
  * planned region count and area as a fraction of 4K,
  * leave-one-out generalisation: plan from 4 timestamps, count alpha>0 pixels of
    the held-out 5th frame that fall outside the plan (must be 0),
  * PNG grid map of the chosen plan.
Usage: roi_analysis.py <frames_dir> <out_dir>
"""
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

sys.path.insert(0, "C:/_DEV/SportCamHUD/Raporty/CPU_P05_ROI_OVERLAY/prototype")
import cpu_hud_roi as roi  # noqa: E402

W, H = 3840, 2160
FRAMES = [0, 80, 160, 240, 319]


def load_alpha(path):
    a = np.fromfile(path, dtype=np.uint8).reshape(H, W, 4)[..., 3]
    return a.copy()


def main():
    fdir, out = Path(sys.argv[1]), Path(sys.argv[2])
    out.mkdir(parents=True, exist_ok=True)
    result = {}
    for layout in ("def", "v10", "v3"):
        alphas = {f: load_alpha(fdir / layout / f"export_hud_f{f}.rgba") for f in FRAMES}
        per = {f: round(100 * float((a > 0).mean()), 3) for f, a in alphas.items()}
        union = roi.alpha_union(alphas.values())
        res = {"alpha_pct_per_frame": per, "alpha_union_pct": round(100 * float(union.mean()), 3),
               "alpha_union_pixels": int(union.sum()), "variants": {}}
        for tile, margin, ov in [(t, m, o) for t in (16, 32, 64) for m in (8, 16, 32) for o in (60_000, 1_400_000)]:
            if True:
                plan = roi.plan_from_mask(union, tile=tile, margin_px=margin, overhead_px=ov, max_regions=24)
                loo = []
                for held in FRAMES:
                    rest = roi.alpha_union(a for f, a in alphas.items() if f != held)
                    p = roi.plan_from_mask(rest, tile=tile, margin_px=margin, overhead_px=ov, max_regions=24)
                    loo.append(roi.uncovered_alpha_pixels(p, alphas[held]))
                cov = roi.coverage_mask(plan)
                res["variants"][f"tile{tile}_margin{margin}_ov{ov // 1000}k"] = {
                    "overlapping_region_pairs": sum(1 for i, a in enumerate(plan.regions) for b in plan.regions[i + 1:]
                                                    if a.x < b.x2 and b.x < a.x2 and a.y < b.y2 and b.y < a.y2),
                    "regions": len(plan.cells), "region_area_px": plan.region_area,
                    "region_pct_of_4k": round(100 * plan.fraction_of_canvas, 2),
                    "atlas_px": plan.atlas_w * plan.atlas_h, "atlas_pct_of_4k": round(100 * plan.atlas_fraction, 2),
                    "uncovered_alpha_union": roi.uncovered_alpha_pixels(plan, union, cov),
                    "leave_one_out_uncovered_alpha_px": loo,
                    "rects": [[r.x, r.y, r.w, r.h] for r in plan.regions]}
        result[layout] = res
        # map image for the production-candidate variant (tile 32, margin 16)
        plan = roi.plan_from_mask(union, tile=16, margin_px=16, overhead_px=60_000, max_regions=24)
        rgb = np.zeros((H // 4, W // 4, 3), dtype=np.uint8)
        rgb[..., :] = (25, 25, 25)
        small = union[::4, ::4]
        rgb[small] = (255, 255, 255)
        im = Image.fromarray(rgb)
        d = ImageDraw.Draw(im)
        for i, r in enumerate(plan.regions):
            d.rectangle([r.x // 4, r.y // 4, r.x2 // 4 - 1, r.y2 // 4 - 1], outline=(255, 80, 0), width=2)
            d.text((r.x // 4 + 4, r.y // 4 + 2), str(i), fill=(255, 255, 0))
        im.save(out / f"roi_map_{layout}_tile16_m16_ov60k.png")
        grid = roi.occupancy_grid(union, 64, 16)
        (out / f"occupancy_grid_{layout}_64px.txt").write_text(
            "\n".join("".join("#" if v else "." for v in row) for row in grid), encoding="utf-8")
    json.dump(result, open(out / "roi_analysis.json", "w"), indent=1)
    for layout, res in result.items():
        print(layout, "alpha union %", res["alpha_union_pct"])
        for k, v in res["variants"].items():
            print(f"  {k:24} regions={v['regions']:2} area={v['region_pct_of_4k']:5.1f}% atlas={v['atlas_pct_of_4k']:5.1f}% "
                  f"uncovered(union)={v['uncovered_alpha_union']} LOO={v['leave_one_out_uncovered_alpha_px']}")


if __name__ == "__main__":
    main()
