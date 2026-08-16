"""ETAP 5R — summarize top50 long frames from etap5r_analysis.json."""
import json
from collections import Counter

d = json.load(open("Raporty/AMD_ETAP5G/etap5r_analysis.json", encoding="utf-8"))
for res in d:
    print(f"=== {res['path']} ===")
    t = res["process_frame_total"]
    print(f"pf_total med={t['median_ms']:.3f} p95={t['p95_ms']:.3f} "
          f"p99={t['p99_ms']:.3f} max={t['max_ms']:.3f} "
          f"accounted={res['accounted_pct']:.1f}% "
          f"vp_unacct_med={res['vp_unaccounted_median_ms']:.4f}")
    print(f"vp_setup med={res['vp_setup']['median_ms']:.3f} "
          f"corr={res['vp_setup']['corr_with_total']:.3f}")
    top = res["top50_long_frames"]
    dom = Counter(e["dominant"] for e in top)
    print(f"TOP50 dominant: {dict(dom)}")
    sr = Counter(e["submit_result"] for e in top)
    print(f"TOP50 submit_result: {dict(sr)}")
    pools = Counter(e["pool"] for e in top)
    print(f"TOP50 pool: {dict(pools)}")
    out = Counter(e["amf_outstanding"] for e in top)
    print(f"TOP50 amf_outstanding: {dict(out)}")
