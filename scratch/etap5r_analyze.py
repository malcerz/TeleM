"""ETAP 5R — analyze native per-frame process_frame trace (CSV).

Reads one or more ``*.frame_accounting.csv`` files and reports:
  * per-substage median / p95 / p99 / max / sum
  * accounted % (sum of exclusive substages vs process_frame_total)
  * AMF outstanding / result-code distribution / input-full rate
  * VP pool-slot analysis (does a specific slot block?)
  * TOP N longest process_frame frames with dominant substage
  * Pearson correlation of process_frame_total vs each substage
Writes a JSON summary alongside.
"""
from __future__ import annotations

import csv
import json
import math
import statistics
import sys
from pathlib import Path

COLS = [
    "frame", "surf_acquire", "vp_total", "vp_setup", "vp_create_view",
    "vp_set_stream", "vp_blt",
    "vp_submit_window", "vp_range_pass",
    "vp_chart_blend", "vp_gauge_blend", "vp_map_blend", "vp_hud_compute",
    "vp_release_view", "amf_create_surface", "amf_submit_input", "amf_query",
    "amf_packet_write", "process_frame_total", "pool_index", "amf_submitted",
    "amf_received", "submit_result", "query_result", "decoder_copy",
]
# Coarse overlapping windows (report separately, not in the disjoint sum).
COARSE = ["vp_total", "vp_setup", "vp_submit_window"]
# Disjoint exclusive substages used for the accounted-% sum.
DISJOINT = ["surf_acquire", "vp_create_view", "vp_set_stream", "vp_blt", "vp_range_pass",
            "vp_chart_blend", "vp_gauge_blend", "vp_map_blend", "vp_hud_compute",
            "vp_release_view", "amf_create_surface", "amf_submit_input",
            "amf_query", "amf_packet_write"]
TIMED = [c for c in COLS if c not in ("frame", "pool_index", "amf_submitted",
                                      "amf_received", "submit_result", "query_result",
                                      "decoder_copy")]


def _pct(sorted_vals, p):
    if not sorted_vals:
        return 0.0
    return sorted_vals[min(len(sorted_vals) - 1, int(p * len(sorted_vals)))]


def _pearson(xs, ys):
    n = len(xs)
    if n < 2:
        return 0.0
    mx = sum(xs) / n
    my = sum(ys) / n
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    dx = math.sqrt(sum((x - mx) ** 2 for x in xs))
    dy = math.sqrt(sum((y - my) ** 2 for y in ys))
    if dx == 0 or dy == 0:
        return 0.0
    return num / (dx * dy)


def analyze(path: Path) -> dict:
    rows = []
    with path.open(encoding="utf-8") as fh:
        rd = csv.DictReader(fh)
        for r in rd:
            row = {k: (float(r[k]) if k in TIMED or k in ("frame", "pool_index") else int(r[k]))
                   for k in COLS}
            rows.append(row)
    n = len(rows)
    if n == 0:
        return {"path": str(path), "frames": 0}

    def col(c):
        return [r[c] for r in rows]

    pf = col("process_frame_total")
    pf_sorted = sorted(pf)

    substages = {}
    for c in TIMED:
        if c == "process_frame_total":
            continue
        vals = col(c)
        sv = sorted(vals)
        substages[c] = {
            "median_ms": statistics.median(vals),
            "p95_ms": _pct(sv, 0.95),
            "p99_ms": _pct(sv, 0.99),
            "max_ms": max(vals),
            "sum_ms": sum(vals),
            "corr_with_total": _pearson(pf, vals),
            "max_frame": rows[vals.index(max(vals))]["frame"],
        }

    # accounted: disjoint exclusive substages vs total
    total_exclusive = [sum(r[c] for c in DISJOINT) for r in rows]
    accounted_pct = statistics.median(
        [te / pf if pf > 0 else 0 for te, pf in zip(total_exclusive, pf)]) * 100.0

    # the unexplained residual inside vp_total (wall not in disjoint VP substages)
    vp_disjoint = [c for c in DISJOINT if c.startswith("vp_")]
    vp_unaccounted = [r["vp_total"] - sum(r[c] for c in vp_disjoint) for r in rows]
    vp_unacct_med = statistics.median(vp_unaccounted)

    # AMF outstanding / results
    outstanding = [s - rc for s, rc in zip(col("amf_submitted"), col("amf_received"))]
    result_dist = {}
    for v in col("submit_result"):
        result_dist[str(int(v))] = result_dist.get(str(int(v)), 0) + 1
    qdist = {}
    for v in col("query_result"):
        qdist[str(int(v))] = qdist.get(str(int(v)), 0) + 1
    input_full_frames = sum(1 for v in col("submit_result") if int(v) == 24)

    # pool slot analysis: submit_input + blt by pool slot
    slots = {}
    for r in rows:
        s = slots.setdefault(int(r["pool_index"]), {"n": 0, "submit": [], "blt": []})
        s["n"] += 1
        s["submit"].append(r["amf_submit_input"])
        s["blt"].append(r["vp_blt"])
    pool_stats = {}
    for s, d in slots.items():
        pool_stats[str(s)] = {
            "n": d["n"],
            "submit_median": statistics.median(d["submit"]),
            "submit_max": max(d["submit"]),
            "blt_median": statistics.median(d["blt"]),
        }

    # TOP long frames
    top_idx = sorted(range(n), key=lambda i: -pf[i])[:50]
    top50 = []
    for i in top_idx:
        r = rows[i]
        parts = {c: r[c] for c in TIMED if c != "process_frame_total"}
        dom = max(parts, key=parts.get)
        top50.append({
            "frame": int(r["frame"]), "total_ms": r["process_frame_total"],
            "dominant": dom, "dominant_ms": parts[dom],
            "pool": int(r["pool_index"]), "amf_outstanding": outstanding[i],
            "submit_result": int(r["submit_result"]),
            "query_result": int(r["query_result"]),
        })

    return {
        "path": str(path), "frames": n,
        "process_frame_total": {
            "median_ms": statistics.median(pf),
            "p95_ms": _pct(pf_sorted, 0.95),
            "p99_ms": _pct(pf_sorted, 0.99),
            "max_ms": max(pf), "max_frame": rows[pf.index(max(pf))]["frame"],
        },
        "substages": substages,
        "vp_unaccounted_median_ms": vp_unacct_med,
        "vp_setup": {
            "median_ms": statistics.median(col("vp_setup")),
            "p95_ms": _pct(sorted(col("vp_setup")), 0.95),
            "max_ms": max(col("vp_setup")),
            "corr_with_total": _pearson(pf, col("vp_setup")),
        },
        "vp_submit_window": {
            "median_ms": statistics.median(col("vp_submit_window")),
            "p95_ms": _pct(sorted(col("vp_submit_window")), 0.95),
            "max_ms": max(col("vp_submit_window")),
            "corr_with_total": _pearson(pf, col("vp_submit_window")),
        },
        "accounted_pct": accounted_pct,
        "amf": {
            "outstanding_median": statistics.median(outstanding),
            "outstanding_max": max(outstanding),
            "submit_result_dist": result_dist,
            "query_result_dist": qdist,
            "input_full_frames": input_full_frames,
        },
        "vp_pool": pool_stats,
        "top50_long_frames": top50,
    }


def main() -> int:
    paths = [Path(p) for p in sys.argv[1:]] or [
        Path("Raporty/AMD_ETAP5G/l5r_B.mp4.frame_accounting.csv")]
    results = []
    for p in paths:
        if not p.exists():
            print(f"MISSING: {p}", flush=True)
            continue
        res = analyze(p)
        results.append(res)
        print(f"\n=== {res['path']} ({res['frames']} frames) ===", flush=True)
        t = res["process_frame_total"]
        print(f"process_frame_total: med={t['median_ms']:.3f} p95={t['p95_ms']:.3f} "
              f"p99={t['p99_ms']:.3f} max={t['max_ms']:.3f} (frame {t['max_frame']})", flush=True)
        print(f"accounted (exclusive sum / total): {res['accounted_pct']:.1f}%", flush=True)
        print(f"\n{'substage':20s} {'med':>8s} {'p95':>8s} {'p99':>8s} {'max':>8s} "
              f"{'corr':>6s}  max@frame", flush=True)
        for name, s in sorted(res["substages"].items(), key=lambda kv: -kv[1]["median_ms"]):
            print(f"{name:20s} {s['median_ms']:8.3f} {s['p95_ms']:8.3f} {s['p99_ms']:8.3f} "
                  f"{s['max_ms']:8.3f} {s['corr_with_total']:6.3f}  {s['max_frame']}", flush=True)
        a = res["amf"]
        print(f"\nAMF outstanding med={a['outstanding_median']} max={a['outstanding_max']} "
              f"input_full_frames={a['input_full_frames']}", flush=True)
        print(f"  submit_result_dist={a['submit_result_dist']} "
              f"query_result_dist={a['query_result_dist']}", flush=True)
        print(f"\nVP pool by slot (submit_input med/max):", flush=True)
        for s, d in sorted(res["vp_pool"].items(), key=lambda kv: int(kv[0])):
            print(f"  slot {s}: n={d['n']} submit_med={d['submit_median']:.3f} "
                  f"submit_max={d['submit_max']:.3f} blt_med={d['blt_median']:.3f}", flush=True)
        print(f"\nTOP 10 long frames:", flush=True)
        for e in res["top50_long_frames"][:10]:
            print(f"  f{e['frame']:4d} total={e['total_ms']:7.3f} dom={e['dominant']}={e['dominant_ms']:.3f} "
                  f"pool={e['pool']} out={e['amf_outstanding']} sr={e['submit_result']} "
                  f"qr={e['query_result']}", flush=True)

    out_json = Path("Raporty/AMD_ETAP5G/etap5r_analysis.json")
    out_json.write_text(json.dumps(results, indent=2, default=str), encoding="utf-8")
    print(f"\nJSON: {out_json}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
