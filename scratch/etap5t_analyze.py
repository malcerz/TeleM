"""ETAP 5T — analyze GPU timestamp timeline + correlate with CPU first-call wait.

Reads ``*.gpu_timeline.csv`` (and optionally the matching ``.frame_accounting.csv``
for CPU wait correlation).  Reports:
  * GPU frame span (median/p95/p99/max)
  * GPU cadence (begin/end interval, equivalent FPS)
  * per-pass GPU time (VP, range, charts, gauge, map, HUD) + % of span + TOP
  * inter-frame GPU overlap (frame N+1 begin < frame N end)
  * ready/disjoint stats, read latency
  * correlation: CPU first-call wait (vp_set_stream / setters) vs GPU prev span,
    GPU cadence, AMF outstanding
Writes Raporty/AMD_ETAP5G/etap5t_analysis.json
"""
from __future__ import annotations

import csv
import json
import math
import statistics
import sys
from pathlib import Path

PASS_COLS = ["vp_ms", "range_ms", "charts_ms", "gauge_ms", "map_ms", "hud_ms"]
PASS_NAMES = {"vp_ms": "VP", "range_ms": "NORMALIZE", "charts_ms": "CHARTS",
              "gauge_ms": "GAUGE", "map_ms": "MAP", "hud_ms": "HUD"}


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


def analyze_gpu(path: Path) -> dict:
    rows = []
    with path.open(encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            rows.append({k: float(r[k]) for k in r})
    n = len(rows)
    if not n:
        return {"gpu": {"frames": 0}}

    span = [r["span_ms"] for r in rows if r["ready"] == 1]
    # begin/end intervals (cadence)
    b_ts = [r["begin_ts"] for r in rows if r["ready"] == 1]
    e_ts = [r["end_ts"] for r in rows if r["ready"] == 1]
    freq = rows[0]["freq"] if rows else 1.0
    begin_interval = [(b_ts[i + 1] - b_ts[i]) / freq * 1000.0 for i in range(len(b_ts) - 1)]
    end_interval = [(e_ts[i + 1] - e_ts[i]) / freq * 1000.0 for i in range(len(e_ts) - 1)]

    # per-pass
    passes = {}
    for c in PASS_COLS:
        vals = [r[c] for r in rows if r["ready"] == 1]
        sv = sorted(vals)
        passes[PASS_NAMES[c]] = {
            "median_ms": statistics.median(vals),
            "p95_ms": _pct(sv, 0.95),
            "p99_ms": _pct(sv, 0.99),
            "max_ms": max(vals),
            "pct_of_span": statistics.median([v / s * 100.0 for v, s in zip(vals, span)]),
        }

    # overlap: frame N+1 begin < frame N end
    overlap = 0
    overlap_ms = []
    for i in range(len(b_ts) - 1):
        gap = (e_ts[i] - b_ts[i + 1]) / freq * 1000.0  # >0 => N+1 began before N ended
        if gap > 0:
            overlap += 1
            overlap_ms.append(gap)

    # ready / disjoint
    ready = sum(1 for r in rows if r["ready"] == 1)
    disjoint = sum(1 for r in rows if r["disjoint"] == 1)
    latency = [r["read_latency"] for r in rows]

    span_sorted = sorted(span)
    return {
        "gpu": {
            "frames": n, "ready": ready, "disjoint": disjoint,
            "span": {"median_ms": statistics.median(span),
                     "p95_ms": _pct(span_sorted, 0.95),
                     "p99_ms": _pct(span_sorted, 0.99),
                     "max_ms": max(span)},
            "cadence": {
                "begin_interval_median_ms": statistics.median(begin_interval),
                "begin_interval_p95_ms": _pct(sorted(begin_interval), 0.95),
                "end_interval_median_ms": statistics.median(end_interval),
                "end_interval_p95_ms": _pct(sorted(end_interval), 0.95),
                "begin_equiv_fps": 1000.0 / statistics.median(begin_interval) if begin_interval else 0.0,
                "end_equiv_fps": 1000.0 / statistics.median(end_interval) if end_interval else 0.0,
            },
            "passes": passes,
            "overlap": {
                "frames_overlapped": overlap,
                "pct": overlap / max(1, len(begin_interval)) * 100.0,
                "overlap_ms_median": statistics.median(overlap_ms) if overlap_ms else 0.0,
                "any": overlap > 0,
            },
            "read_latency_median": statistics.median(latency) if latency else None,
            "freq": freq,
        }
    }


def analyze_cpu(path: Path) -> dict:
    """Read the 5R/5S CPU trace: per-frame first-call wait (setters/set_stream)
    + process_frame total + AMF outstanding."""
    rows = []
    with path.open(encoding="utf-8") as fh:
        rd = csv.DictReader(fh)
        for r in rd:
            rows.append({
                "frame": int(float(r["frame"])),
                "cpu_wait": float(r.get("vp_set_stream", 0.0) or 0.0),
                "setters": (float(r.get("vp_setter_fmt", 0.0) or 0.0)
                            + float(r.get("vp_setter_src_rect", 0.0) or 0.0)
                            + float(r.get("vp_setter_dst_rect", 0.0) or 0.0)),
                "pf_total": float(r["process_frame_total"]),
                "amf_out": int(r["amf_submitted"]) - int(r["amf_received"]),
            })
    return {r["frame"]: r for r in rows}


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("gpu_csv")
    ap.add_argument("--cpu-csv", default=None)
    args = ap.parse_args()

    res = analyze_gpu(Path(args.gpu_csv))
    g = res["gpu"]
    print(f"=== GPU TIMELINE {args.gpu_csv} ({g['frames']} frames; ready {g['ready']}, "
          f"disjoint {g['disjoint']}, read_latency_med {g['read_latency_median']}) ===")
    s = g["span"]
    print(f"GPU frame span: med={s['median_ms']:.3f} p95={s['p95_ms']:.3f} "
          f"p99={s['p99_ms']:.3f} max={s['max_ms']:.3f} ms")
    c = g["cadence"]
    print(f"GPU cadence: begin_interval med={c['begin_interval_median_ms']:.3f} "
          f"p95={c['begin_interval_p95_ms']:.3f} (equiv {c['begin_equiv_fps']:.2f} FPS), "
          f"end_interval med={c['end_interval_median_ms']:.3f} (equiv {c['end_equiv_fps']:.2f} FPS)")
    print(f"GPU passes (med / p95 / %span):")
    top = sorted(g["passes"].items(), key=lambda kv: -kv[1]["median_ms"])
    for name, p in top:
        print(f"  {name:10s} med={p['median_ms']:8.3f} p95={p['p95_ms']:8.3f} "
              f"p99={p['p99_ms']:8.3f} max={p['max_ms']:8.3f} %span={p['pct_of_span']:5.1f}")
    ov = g["overlap"]
    print(f"Overlap: any={ov['any']} frames={ov['frames_overlapped']} "
          f"({ov['pct']:.1f}%) overlap_ms_med={ov['overlap_ms_median']:.3f}")

    if args.cpu_csv:
        cpu = analyze_cpu(Path(args.cpu_csv))
        # merge by frame
        gpu_by_frame = {}
        with open(args.gpu_csv, encoding="utf-8") as fh:
            for r in csv.DictReader(fh):
                gpu_by_frame[int(float(r["frame"]))] = r
        common = sorted(set(cpu.keys()) & set(gpu_by_frame.keys()))
        xs_prev_span, ys_wait = [], []
        xs_cadence, ys_wait2 = [], []
        xs_amf, ys_wait3 = [], []
        prev_span = {}
        prev_end = {}
        for f in common:
            gr = gpu_by_frame[f]
            if float(gr["ready"]) != 1:
                continue
            wait = cpu[f]["cpu_wait"]
            amf = cpu[f]["amf_out"]
            # GPU previous frame span = span of frame f-1 (the work that finished
            # right before this frame's CPU wait)
            pspan = prev_span.get(f - 1)
            pend = prev_end.get(f - 1)
            if pspan is not None:
                xs_prev_span.append(pspan); ys_wait.append(wait); ys_amf3 = ys_wait3
            if pend is not None:
                xs_cadence.append(pend); ys_wait2.append(wait)
            xs_amf.append(amf); ys_wait3.append(wait)
            prev_span[f] = float(gr["span_ms"])
            prev_end[f] = float(gr["end_ts"]) / float(gr["freq"]) * 1000.0

        res["cpu_correlation"] = {
            "n": len(ys_wait),
            "wait_vs_prev_gpu_span": _pearson(xs_prev_span, ys_wait) if len(ys_wait) > 2 else None,
            "wait_vs_prev_gpu_end": _pearson(xs_cadence, ys_wait2) if len(ys_wait2) > 2 else None,
            "wait_vs_amf_outstanding": _pearson(xs_amf, ys_wait3) if len(ys_wait3) > 2 else None,
        }
        cr = res["cpu_correlation"]
        print(f"\nCPU-wait correlation (n={cr['n']}):")
        print(f"  wait vs prev GPU span: {cr['wait_vs_prev_gpu_span']}")
        print(f"  wait vs prev GPU end:  {cr['wait_vs_prev_gpu_end']}")
        print(f"  wait vs AMF outstanding: {cr['wait_vs_amf_outstanding']}")

    out = Path("Raporty/AMD_ETAP5G/etap5t_analysis.json")
    out.write_text(json.dumps(res, indent=2, default=str), encoding="utf-8")
    print(f"\nJSON: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
