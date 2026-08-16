"""ETAP 5S — analyze native trace: per-setter VP timers, decoder-surface reuse,
output-slot correlation, STATIC_CACHE effect + sync migration.

Reads one or more ``*.frame_accounting.csv`` (5S schema) and reports:
  * per VideoProcessorSetStream* setter: median/p95/p99/max + corr with pf_total
  * stream-state signature distinct count (proves static/dynamic)
  * setters_skipped distribution (STATIC_CACHE)
  * decoder input surface: unique ids, reuse distance, corr of set_stream wait
    with "distance since same decoder texture last used"
  * VP output slot: set_stream wait by slot
  * AMF mapping: vp_out_tex_id -> submitted/received lifecycle
  * TOP long frames with decoder id / output slot / AMF outstanding
"""
from __future__ import annotations

import csv
import json
import math
import statistics
import sys
from pathlib import Path

COLS = [
    "frame", "surf_acquire", "vp_total", "vp_setup", "vp_create_view", "vp_set_stream",
    "vp_setter_fmt", "vp_setter_src_rect", "vp_setter_dst_rect", "vp_blt",
    "vp_submit_window", "vp_range_pass",
    "vp_chart_blend", "vp_gauge_blend", "vp_map_blend", "vp_hud_compute",
    "vp_release_view", "amf_create_surface", "amf_submit_input", "amf_query",
    "amf_packet_write", "process_frame_total", "pool_index", "decoder_tex_id",
    "vp_out_tex_id", "array_index", "setters_skipped", "state_sig", "amf_submitted",
    "amf_received", "submit_result", "query_result", "decoder_copy",
]
SETTERS = ["vp_setter_fmt", "vp_setter_src_rect", "vp_setter_dst_rect"]
TIME_COLS = [c for c in COLS if c not in (
    "frame", "pool_index", "decoder_tex_id", "vp_out_tex_id", "array_index",
    "setters_skipped", "state_sig", "amf_submitted", "amf_received",
    "submit_result", "query_result", "decoder_copy")]


def _pct(sv, p):
    return sv[min(len(sv) - 1, int(p * len(sv)))] if sv else 0.0


def _pearson(xs, ys):
    n = len(xs)
    if n < 2:
        return 0.0
    mx, my = sum(xs) / n, sum(ys) / n
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    dx = math.sqrt(sum((x - mx) ** 2 for x in xs))
    dy = math.sqrt(sum((y - my) ** 2 for y in ys))
    if dx == 0 or dy == 0:
        return 0.0
    return num / (dx * dy)


def analyze(path: Path) -> dict:
    rows = []
    with path.open(encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            rows.append({k: (float(r[k]) if k in TIME_COLS or k == "frame" else int(float(r[k])))
                         for k in COLS})
    n = len(rows)
    if not n:
        return {"path": str(path), "frames": 0}

    pf = [r["process_frame_total"] for r in rows]

    setter_stats = {}
    for c in SETTERS:
        vals = [r[c] for r in rows]
        sv = sorted(vals)
        setter_stats[c] = {
            "median_ms": statistics.median(vals),
            "p95_ms": _pct(sv, 0.95),
            "p99_ms": _pct(sv, 0.99),
            "max_ms": max(vals),
            "sum_ms": sum(vals),
            "corr_with_total": _pearson(pf, vals),
            "pct_nonzero": sum(1 for v in vals if v > 0.01) / n * 100.0,
        }

    setters_total = [sum(r[c] for c in SETTERS) for r in rows]
    setters_skipped = sum(1 for r in rows if r["setters_skipped"] == 1)

    # state signature
    sigs = set(r["state_sig"] for r in rows)

    # decoder input surface reuse
    dec_ids = set(r["decoder_tex_id"] for r in rows)
    last_seen = {}
    reuse_dist = []
    for r in rows:
        did = r["decoder_tex_id"]
        if did in last_seen:
            reuse_dist.append(r["frame"] - last_seen[did])
        else:
            reuse_dist.append(-1)  # first occurrence
        last_seen[did] = r["frame"]
    first_occurrence = [i for i, d in enumerate(reuse_dist) if d == -1]
    corr_reuse = _pearson([d if d > 0 else 0 for d in reuse_dist], setters_total)

    # set_stream wait vs decoder surface "freshness": was the surface seen in the
    # last K frames (i.e., being reused while still possibly in use)?
    # 'reuse_in_window' = 1 when the same decoder texture was used <=4 frames ago.
    reuse_window = []
    for i, r in enumerate(rows):
        did = r["decoder_tex_id"]
        back = 0
        for j in range(max(0, i - 8), i):
            if rows[j]["decoder_tex_id"] == did:
                back = i - j
                break
        reuse_window.append(1 if 0 < back <= 4 else 0)
    corr_window = _pearson(reuse_window, setters_total)

    # output slot correlation
    slot_stats = {}
    for r in rows:
        s = slot_stats.setdefault(r["pool_index"], {"n": 0, "setstream": []})
        s["n"] += 1
        s["setstream"].append(setters_total[rows.index(r)])
    slot_out = {str(k): {"n": v["n"], "setstream_median": statistics.median(v["setstream"]),
                         "setstream_max": max(v["setstream"])}
                for k, v in slot_stats.items()}

    # AMF mapping: vp_out_tex_id -> (first_submitted_frame, releases)
    amf_map = {}
    for r in rows:
        oid = r["vp_out_tex_id"]
        amf_map.setdefault(oid, []).append(r["frame"])
    # outstanding when each vp_out_tex_id is reused by VP (i.e., outTex reused)
    out_reuse_wait = []
    last_sub = {}
    for r in rows:
        oid = r["vp_out_tex_id"]
        if oid in last_sub:
            # the texture was submitted to AMF at last_sub; now VP writes again
            out_reuse_wait.append(r["frame"] - last_sub[oid])
        else:
            out_reuse_wait.append(-1)
        last_sub[oid] = r["frame"]

    # TOP long frames
    top = sorted(range(n), key=lambda i: -pf[i])[:50]
    top50 = []
    for i in top:
        r = rows[i]
        parts = {c: r[c] for c in SETTERS + ["vp_blt", "vp_submit_window", "amf_submit_input"]}
        dom = max(parts, key=parts.get)
        top50.append({
            "frame": int(r["frame"]), "total_ms": r["process_frame_total"],
            "dominant": dom, "dominant_ms": parts[dom],
            "decoder_tex_id": int(r["decoder_tex_id"]), "output_slot": int(r["pool_index"]),
            "vp_out_tex_id": int(r["vp_out_tex_id"]),
            "amf_outstanding": int(r["amf_submitted"] - r["amf_received"]),
            "setters_skipped": int(r["setters_skipped"]),
        })

    pf_sorted = sorted(pf)
    return {
        "path": str(path), "frames": n,
        "process_frame_total": {
            "median_ms": statistics.median(pf), "p95_ms": _pct(pf_sorted, 0.95),
            "p99_ms": _pct(pf_sorted, 0.99), "max_ms": max(pf)},
        "setters": setter_stats,
        "setters_total": {
            "median_ms": statistics.median(setters_total),
            "p95_ms": _pct(sorted(setters_total), 0.95),
            "max_ms": max(setters_total),
            "corr_with_total": _pearson(pf, setters_total)},
        "setters_skipped": setters_skipped,
        "state_sig_distinct": len(sigs),
        "blt": {
            "median_ms": statistics.median([r["vp_blt"] for r in rows]),
            "p95_ms": _pct(sorted([r["vp_blt"] for r in rows]), 0.95),
            "max_ms": max(r["vp_blt"] for r in rows),
            "corr_with_total": _pearson(pf, [r["vp_blt"] for r in rows])},
        "decoder_input": {
            "unique_surfaces": len(dec_ids),
            "first_occurrences": len(first_occurrence),
            "reuse_distance_median": statistics.median([d for d in reuse_dist if d > 0]) if any(d > 0 for d in reuse_dist) else None,
            "corr_setstream_with_reuse_dist": corr_reuse,
            "corr_setstream_with_reuse_in_4": corr_window},
        "vp_output": {"pool_size": 4, "by_slot": slot_out},
        "amf_lifetime": {
            "vp_out_tex_unique": len(amf_map),
            "vp_out_reuse_gap_median": statistics.median([g for g in out_reuse_wait if g > 0]) if any(g > 0 for g in out_reuse_wait) else None,
            "exact_release_observed": False,
        },
        "top50": top50,
    }


def main() -> int:
    paths = [Path(p) for p in sys.argv[1:]]
    results = []
    for p in paths:
        if not p.exists():
            print(f"MISSING: {p}", flush=True)
            continue
        res = analyze(p)
        results.append(res)
        t = res["process_frame_total"]
        print(f"\n=== {res['path']} ({res['frames']} frames) ===", flush=True)
        print(f"pf_total: med={t['median_ms']:.3f} p95={t['p95_ms']:.3f} "
              f"p99={t['p99_ms']:.3f} max={t['max_ms']:.3f}", flush=True)
        print(f"state_sig distinct: {res['state_sig_distinct']}  "
              f"setters_skipped: {res['setters_skipped']}", flush=True)
        st = res["setters_total"]
        print(f"setters_total: med={st['median_ms']:.3f} p95={st['p95_ms']:.3f} "
              f"max={st['max_ms']:.3f} corr={st['corr_with_total']:.3f}", flush=True)
        for c, s in res["setters"].items():
            print(f"  {c:22s} med={s['median_ms']:8.3f} p95={s['p95_ms']:8.3f} "
                  f"p99={s['p99_ms']:8.3f} max={s['max_ms']:8.3f} "
                  f"corr={s['corr_with_total']:6.3f} nonzero%={s['pct_nonzero']:.1f}", flush=True)
        b = res["blt"]
        print(f"blt: med={b['median_ms']:.3f} p95={b['p95_ms']:.3f} max={b['max_ms']:.3f} "
              f"corr={b['corr_with_total']:.3f}", flush=True)
        di = res["decoder_input"]
        print(f"decoder input: unique={di['unique_surfaces']} first={di['first_occurrences']} "
              f"reuse_dist_med={di['reuse_distance_median']} "
              f"corr_setstream_reuse_dist={di['corr_setstream_with_reuse_dist']:.3f} "
              f"corr_setstream_reuse_in_4={di['corr_setstream_with_reuse_in_4']:.3f}", flush=True)
        print("vp_output by slot (setstream med/max):", flush=True)
        for s, d in sorted(res["vp_output"]["by_slot"].items(), key=lambda kv: int(kv[0])):
            print(f"  slot {s}: n={d['n']} med={d['setstream_median']:.3f} max={d['setstream_max']:.3f}",
                  flush=True)
        al = res["amf_lifetime"]
        print(f"amf lifetime: vp_out_tex_unique={al['vp_out_tex_unique']} "
              f"vp_out_reuse_gap_med={al['vp_out_reuse_gap_median']} "
              f"exact_release_observed={al['exact_release_observed']}", flush=True)
        print("TOP 8 long:", flush=True)
        for e in res["top50"][:8]:
            print(f"  f{e['frame']:4d} tot={e['total_ms']:7.3f} dom={e['dominant']}={e['dominant_ms']:.3f} "
                  f"dec={e['decoder_tex_id']:#x} slot={e['output_slot']} "
                  f"out={e['amf_outstanding']} skip={e['setters_skipped']}", flush=True)

    Path("Raporty/AMD_ETAP5G/etap5s_analysis.json").write_text(
        json.dumps(results, indent=2, default=str), encoding="utf-8")
    print(f"\nJSON: Raporty/AMD_ETAP5G/etap5s_analysis.json", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
