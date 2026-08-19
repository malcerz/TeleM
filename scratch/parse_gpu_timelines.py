"""Parse GPU timeline CSV files for ETAP 8H."""
import csv
import glob
from pathlib import Path
import numpy as np

root = Path("c:/_DEV/TeleM")

files = glob.glob(str(root / "scratch" / "*.gpu_timeline.csv"))
print(f"Found {len(files)} GPU timeline CSV files.")

def percentile(arr, q):
    return np.percentile(arr, q)

print("\n=== DETAILED GPU TIMESTAMPS SUMMARY (MEDIAN / P95 / P99 MS) ===")
print(f"{'Run / File':35s} | {'Span (total)':16s} | {'VideoProc Blt':16s} | {'Range Normalize':16s} | {'Map Resample+Bld':16s} | {'HUD Direct NV12':16s}")
print("-" * 125)

for f in sorted(files):
    name = Path(f).name.replace(".mp4.gpu_timeline.csv", "")
    rows = []
    with open(f, "r") as fh:
        reader = csv.DictReader(fh)
        for r in reader:
            rows.append(r)
    if not rows:
        continue
    
    span = [float(r["span_ms"]) for r in rows]
    vp = [float(r["vp_ms"]) for r in rows]
    rng = [float(r["range_ms"]) for r in rows]
    m_cs = [float(r["map_ms"]) for r in rows]
    hud = [float(r["hud_ms"]) for r in rows]
    
    print(f"{name:35s} | {np.median(span):5.2f}/{percentile(span,95):5.2f}/{percentile(span,99):5.2f} | {np.median(vp):5.2f}/{percentile(vp,95):5.2f}/{percentile(vp,99):5.2f} | {np.median(rng):5.2f}/{percentile(rng,95):5.2f}/{percentile(rng,99):5.2f} | {np.median(m_cs):5.2f}/{percentile(m_cs,95):5.2f}/{percentile(m_cs,99):5.2f} | {np.median(hud):5.2f}/{percentile(hud,95):5.2f}/{percentile(hud,99):5.2f}")
