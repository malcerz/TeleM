"""ETAP 5M — aggregate GPU engine utilization CSV."""
import csv
import statistics

p = "Raporty/AMD_ETAP5G/etap5m_gpu_util.csv"
rows = list(csv.DictReader(open(p, encoding="utf-8")))
print(f"gpu engine samples: {len(rows)}")
for c in ("gpu_3d", "gpu_decode", "gpu_encode", "gpu_copy", "gpu_other"):
    vals = []
    for r in rows:
        try:
            vals.append(float(r[c]))
        except (ValueError, TypeError):
            pass
    if vals:
        print(f"  {c:12s} avg={statistics.fmean(vals):6.1f}  med={statistics.median(vals):6.1f}  max={max(vals):6.1f}  p95={sorted(vals)[min(len(vals)-1,int(len(vals)*0.95))]:6.1f}")
