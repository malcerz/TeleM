"""AMD ETAP 2B gauge variability analysis (mandated stats + rect proposal)."""
import json
import sys
from pathlib import Path

import numpy as np

DEFAULT = str(Path(__file__).resolve().parent.parent /
              "scratch/etap2b_test/var.mp4.gauge_variability.json")
MARGIN = 12


def pct(vals, q):
    s = sorted(vals)
    return float(s[min(len(s) - 1, int(q * len(s)))]) if s else 0.0


def row(name, vals):
    if not vals:
        print(f"  {name:26s} n/a")
        return
    print(f"  {name:26s} avg={sum(vals)/len(vals):10.1f} "
          f"median={pct(vals,.5):10.1f} p95={pct(vals,.95):10.1f} max={max(vals):10.1f}")


def overlap(a, b):
    return (a[0] < b[0]+b[2] and b[0] < a[0]+a[2]
            and a[1] < b[1]+b[3] and b[1] < a[1]+a[3])


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else DEFAULT
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    recs = [r for r in data["records"] if "changed_px" in r]
    summ = data.get("summary", {})
    tw, th = int(summ["tile_w"]), int(summ["tile_h"])
    full_bytes = tw * th * 4
    print(f"tile={tw}x{th} ({full_bytes/1e6:.2f} MB) measured="
          f"{summ['frames_measured']} diffable={len(recs)}")

    hashes = [(r["frame"], r["md5"]) for r in data["records"]]
    trans = [f1 for (_f0, h0), (f1, h1) in zip(hashes, hashes[1:]) if h0 != h1]
    print(f"unique_full_tile_md5={len({h for _, h in hashes})} "
          f"transitions={len(trans)} frames={trans[:20]}")

    changed = [float(r["changed_px"]) for r in recs]
    bw = [float(r["bbox_bytes"]) for r in recs if r["bbox_bytes"] > 0]
    dims = [r["bbox_local"] for r in recs if r["bbox_local"]]
    print("changed_pixels / tight_changed_bbox:")
    row("changed_px", changed)
    row("bbox_w", [float(d[2]) for d in dims])
    row("bbox_h", [float(d[3]) for d in dims])
    row("bbox_bytes", bw)
    row("asarray_ms(probe)", [r["asarray_ms"] for r in data["records"]])
    med_bb = pct(bw, .5)
    p95_bb = pct(bw, .95)
    print(f"  bytes/frame: tight_median={med_bb:,.0f} tight_p95={p95_bb:,.0f} "
          f"full_tile={full_bytes:,}")

    # Union approximation from per-frame tight bboxes (design-level precision).
    u = np.zeros((th, tw), dtype=bool)
    hits = np.zeros((th, tw), dtype=np.uint16)
    for r in recs:
        if r["bbox_local"]:
            x, y, w, h = r["bbox_local"]
            u[y:y+h, x:x+w] = True
            hits[y:y+h, x:x+w] += 1
    n = max(1, len(recs))
    needle_px = int((hits >= 0.5 * n).sum())
    value_px = int(((hits >= max(2, int(0.02 * n))) & (hits < 0.5 * n)).sum())
    rare_px = int(((hits > 0) & (hits < max(2, int(0.02 * n)))).sum())
    ub = summ.get("union_bbox_local")
    print(f"classification(px-hits based): needle>=50%f={needle_px:,} "
          f"value=2..50%f={value_px:,} rare<2%f={rare_px:,}")
    print(f"union_bbox_coverage={100.0*u.mean():.3f}% tile; exact_union_px="
          f"{summ.get('union_changed_px')} density%={summ.get('union_density_pct')}")
    if ub:
        print(f"union_tight_bbox={ub} area_bytes={ub[2]*ub[3]*4:,}")

    # Proposed fixed rects: connected components on S=8 downscaled union.
    S = 8
    gh, gw = (th + S - 1)//S, (tw + S - 1)//S
    grid = u[:gh*S, :gw*S].reshape(gh, S, gw, S).any(axis=(1, 3))
    seen = np.zeros_like(grid, dtype=bool)
    boxes = []
    for gy in range(gh):
        for gx in range(gw):
            if grid[gy, gx] and not seen[gy, gx]:
                stack, ys, xs = [(gy, gx)], [], []
                seen[gy, gx] = True
                while stack:
                    cy, cx = stack.pop()
                    ys.append(cy); xs.append(cx)
                    for dy in (-1, 0, 1):
                        for dx in (-1, 0, 1):
                            ny, nx = cy+dy, cx+dx
                            if (0 <= ny < gh and 0 <= nx < gw
                                    and grid[ny, nx] and not seen[ny, nx]):
                                seen[ny, nx] = True
                                stack.append((ny, nx))
                boxes.append([min(xs)*S, min(ys)*S,
                              (max(xs)-min(xs)+1)*S, (max(ys)-min(ys)+1)*S])
    grown = []
    for x, y, w, h in sorted(boxes, key=lambda r: -(r[2]*r[3])):
        cand = [max(0, x-MARGIN), max(0, y-MARGIN), 0, 0]
        cand[2] = min(tw, x+w+MARGIN) - cand[0]
        cand[3] = min(th, y+h+MARGIN) - cand[1]
        merged_into = False
        for o in grown:
            if overlap(cand, o):
                nx1 = max(o[0]+o[2], cand[0]+cand[2])
                ny1 = max(o[1]+o[3], cand[1]+cand[3])
                o[0], o[1] = min(o[0], cand[0]), min(o[1], cand[1])
                o[2], o[3] = nx1-o[0], ny1-o[1]
                merged_into = True
                break
        if not merged_into:
            grown.append(cand)
    total = sum(w*h for _, _, w, h in grown)
    cov = sum(int(u[y:y+h, x:x+w].sum()) for x, y, w, h in grown)
    upx = int(u.sum())
    print(f"proposed_rects k={len(grown)} margin={MARGIN}:")
    for x, y, w, h in grown:
        print(f"  rect=({x},{y},{w},{h}) bytes={w*h*4:,}")
    print(f"rect_total_bytes/frame={total*4:,} "
          f"({100.0*total*4/full_bytes:.1f}% of full tile)")
    print(f"rect_set_covers_union={'YES' if cov == upx else f'{100.0*cov/max(1,upx):.4f}%'}")
    env = ";".join(f"{x},{y},{w},{h}" for x, y, w, h in grown)
    print(f'AMD_GAUGE_DYNAMIC_RECTS="{env}"')


if __name__ == "__main__":
    main()
