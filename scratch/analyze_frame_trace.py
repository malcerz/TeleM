"""Analyze the 4K frame_trace.csv accounting (Part A).

For each frame: frame_total, producer children sum, consumer children sum,
unaccounted.  Reports median/mean/p95/p99 and the frame distribution.
"""
import csv
import statistics

def pct(vals, p):
    x = sorted(vals)
    return x[min(len(x) - 1, int(len(x) * p))]

def summarize(name, path):
    rows = list(csv.DictReader(open(path, encoding="utf-8")))
    print("=" * 90)
    print("CASE:", name, " frames:", len(rows))
    ft = [float(r["frame_total_ms"]) for r in rows]
    prod = [float(r["producer_ms"]) for r in rows]
    cons = [float(r["consumer_ms"]) for r in rows]
    gap = [float(r["inter_frame_gap_ms"]) for r in rows]

    def rep(label, vals):
        print("  %-22s mean=%9.2f  med=%9.2f  p95=%9.2f  p99=%9.2f  max=%9.2f" % (
            label, statistics.fmean(vals), statistics.median(vals),
            pct(vals, 0.95), pct(vals, 0.99), max(vals)))

    rep("frame_total_ms", ft)
    rep("producer_ms", prod)
    rep("consumer_ms", cons)
    rep("inter_frame_gap_ms", gap)

    # producer children sum
    pkeys = [k for k in rows[0] if k.startswith("p_")]
    ckeys = [k for k in rows[0] if k.startswith("c_")]
    psum = []
    csum = []
    for r in rows:
        ps = sum(float(r[k]) for k in pkeys if r[k] not in ("", None))
        cs = sum(float(r[k]) for k in ckeys if r[k] not in ("", None))
        psum.append(ps)
        csum.append(cs)
    rep("producer_children_sum", psum)
    rep("consumer_children_sum", csum)
    # unaccounted
    unacct_prod = [prod[i] - psum[i] for i in range(len(rows))]
    unacct_cons = [cons[i] - csum[i] for i in range(len(rows))]
    unacct_total = [ft[i] - (psum[i] + csum[i]) for i in range(len(rows))]
    rep("producer_unaccounted", unacct_prod)
    rep("consumer_unaccounted", unacct_cons)
    rep("total_unaccounted (frame - sum children)", unacct_total)

    # frame distribution buckets
    buckets = {"<25": 0, "25-50": 0, "50-100": 0, "100-200": 0, "200-500": 0, ">500": 0}
    for v in ft:
        if v < 25: buckets["<25"] += 1
        elif v < 50: buckets["25-50"] += 1
        elif v < 100: buckets["50-100"] += 1
        elif v < 200: buckets["100-200"] += 1
        elif v < 500: buckets["200-500"] += 1
        else: buckets[">500"] += 1
    print("  frame_total distribution:", buckets)
    # consumer children detail (median of the main ones)
    print("  consumer children (median ms):")
    for k in ("c_MF ReadSample/decode availability", "c_consumer_upload",
              "c_consumer_native_call", "c_VideoProcessor CPU submit",
              "c_VideoProcessor GPU completion", "c_GPU wait/synchronization",
              "c_AMF submit/backpressure", "c_AMF QueryOutput", "c_Packet write",
              "c_pipeline_total"):
        vals = [float(r[k]) for r in rows if r.get(k) not in ("", None)]
        if vals:
            print("    %-44s med=%8.2f  mean=%8.2f  max=%8.2f" % (k, statistics.median(vals), statistics.fmean(vals), max(vals)))
    print("  producer children (median ms):")
    for k in pkeys:
        vals = [float(r[k]) for r in rows if r.get(k) not in ("", None)]
        if vals:
            print("    %-44s med=%8.2f  mean=%8.2f" % (k, statistics.median(vals), statistics.fmean(vals)))
    return rows

rows_full = summarize("account_4k_full_300f",
                      r"Raporty/AMD_RENDER_PATH_AUDIT/account_4k_full_300f.mp4.frame_trace.csv")
rows_nohud = summarize("account_4k_nohud_300f",
                       r"Raporty/AMD_RENDER_PATH_AUDIT/account_4k_nohud_300f.mp4.frame_trace.csv")
