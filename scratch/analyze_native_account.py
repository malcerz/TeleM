"""Analyze native frame_accounting.csv for 4K: spikes and VP substage breakdown."""
import csv
import statistics
from collections import Counter

def analyze(name, path):
    rows = list(csv.DictReader(open(path, encoding="utf-8")))
    print("=" * 90)
    print("NATIVE FRAME ACCOUNTING:", name, " frames:", len(rows))
    def f(r, k):
        v = r.get(k, "")
        return float(v) if v not in ("", None) else 0.0
    tot = [f(r, "process_frame_total") for r in rows]
    vpt = [f(r, "vp_total") for r in rows]
    print("  process_frame_total: mean=%.2f med=%.2f p95=%.2f p99=%.2f max=%.2f" % (
        statistics.fmean(tot), statistics.median(tot),
        sorted(tot)[int(len(tot)*0.95)], sorted(tot)[int(len(tot)*0.99)], max(tot)))
    print("  vp_total:            mean=%.2f med=%.2f p95=%.2f max=%.2f" % (
        statistics.fmean(vpt), statistics.median(vpt),
        sorted(vpt)[int(len(vpt)*0.95)], max(vpt)))
    idx = sorted(range(len(rows)), key=lambda i: tot[i], reverse=True)[:8]
    print("  Top spike frames (process_frame_total):")
    for i in idx:
        r = rows[i]
        print("    fr=%4s total=%9.1f vp_total=%9.1f vp_blt=%9.1f submit_win=%9.1f "
              "amf_submit=%7.2f amf_query=%6.2f retries=%s amf_sub=%s amf_recv=%s" % (
            r.get("frame"), f(r, "process_frame_total"), f(r, "vp_total"), f(r, "vp_blt"),
            f(r, "vp_submit_window"), f(r, "amf_submit_input"), f(r, "amf_query"),
            r.get("retries"), r.get("amf_submitted"), r.get("amf_received")))
    print("  Median substages (ms):")
    for k in ("surf_acquire", "vp_total", "vp_blt", "vp_submit_window", "vp_range_pass",
              "clear_prev_above", "vp_chart_blend", "vp_gauge_blend", "map_resample",
              "vp_map_blend", "above_blend", "flush_total", "vp_hud_compute",
              "amf_create_surface", "amf_submit_input", "amf_query", "amf_packet_write"):
        vals = [f(r, k) for r in rows]
        print("    %-20s med=%9.3f mean=%9.3f max=%9.3f" % (k, statistics.median(vals), statistics.fmean(vals), max(vals)))
    retries = sum(f(r, "retries") for r in rows)
    print("  total AMF retries (input_full backpressure):", retries)
    b = Counter()
    for v in vpt:
        if v < 10: b["<10"] += 1
        elif v < 20: b["10-20"] += 1
        elif v < 50: b["20-50"] += 1
        elif v < 100: b["50-100"] += 1
        elif v < 500: b["100-500"] += 1
        else: b[">500"] += 1
    print("  vp_total distribution:", dict(b))

analyze("account_4k_nohud_300f",
        r"Raporty/AMD_RENDER_PATH_AUDIT/account_4k_nohud_300f.mp4.frame_accounting.csv")
analyze("account_4k_full_300f",
        r"Raporty/AMD_RENDER_PATH_AUDIT/account_4k_full_300f.mp4.frame_accounting.csv")
