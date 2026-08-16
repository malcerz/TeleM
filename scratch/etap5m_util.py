"""ETAP 5M — aggregate CPU/GPU utilization samples (CSV from sampler)."""
import csv
import statistics
from pathlib import Path

p = Path(r"Raporty/AMD_ETAP5G/etap5m_util_samples.csv")
if not p.exists():
    print("no samples CSV yet")
    raise SystemExit(0)

rows = list(csv.DictReader(open(p, encoding="utf-8")))
print(f"samples: {len(rows)}")
cols = ["cpu_total", "cpu_py_raw", "cpu_py_norm", "gpu_3d", "gpu_decode", "gpu_encode", "gpu_copy"]
for c in cols:
    vals = []
    for r in rows:
        v = r.get(c, "")
        if v in ("", None):
            continue
        try:
            vals.append(float(v))
        except ValueError:
            pass
    if vals:
        avg = statistics.fmean(vals)
        mx = max(vals)
        p99 = sorted(vals)[min(len(vals) - 1, int(len(vals) * 0.99))]
        med = statistics.median(vals)
        print(f"  {c:14s} avg={avg:6.1f}  med={med:6.1f}  max={mx:6.1f}  p99={p99:6.1f}")
