"""ETAP 5M — print per-run stage timings from the baseline JSON."""
import json
from pathlib import Path

d = json.load(open(r"Raporty/AMD_ETAP5G/etap5m_baseline.json", encoding="utf-8"))
runs = d["runs"]
tags = ("A", "B", "C", "D")
keys = list(runs["A"]["stage_med"].keys())

print(f"{'stage':34s}" + "".join(f"{t:>10s}" for t in tags))
for k in keys:
    vals = [runs[t]["stage_med"][k] for t in tags]
    print(f"{k:34s}" + "".join(f"{v:10.3f}" for v in vals))

print()
print("bytes per frame:")
for t in tags:
    r = runs[t]
    print(
        f"{t}: fps={r['true_fps']:.3f} wall={r['wall']:.2f} "
        f"gauge_mib={r['gauge_upload_mib']:.4f} map_mib={r['map_upload_mib']:.4f} "
        f"drops={r['drops']}"
    )
