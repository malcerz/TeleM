"""Reproduce AMD Final vs Preview FIT temperature parity on the user's export.

Compares the AMD final render-prep cache column (render_preparation vectorized
builder) with the canonical Preview resolver (resolve_current_presentation)
for the same frame timestamps.
"""
import json, sys
from datetime import timedelta
from pathlib import Path
import numpy as np
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from telemetry_fit import parse_fit
from src.render_telemetry_cache import RenderTelemetryCache
from src.telemetry_resolver import resolve_current_presentation

cache_dir, fit_path = Path(sys.argv[1]), Path(sys.argv[2])
c = RenderTelemetryCache.load(cache_dir / "manifest.json", mmap=True)
recs = parse_fit(fit_path)
samples = recs.field_catalog["temperature"]["samples"]
col = None
for it in c._fit_items:
    if it[0] == "fit_temperature_text":
        col = np.asarray(it[1], dtype=float)
base = c.base_dt
layout = json.load(open("def_layout.json", encoding="utf-8"))
cfg = layout["indicators"]["fit_temperature_text"]
fps = c.fps
idx = list(range(0, c.frames, max(1, c.frames // 400)))
diffs, out = [], []
for i in idx:
    dt = base + timedelta(seconds=round(i / fps * 1e6) / 1e6)
    pv = resolve_current_presentation(samples, dt, "temperature", cfg)
    fv = col[i]
    if pv is not None and not np.isnan(fv):
        diffs.append(abs(pv - fv))
        out.append((i, round(pv, 3), round(float(fv), 3), f"{pv:.1f}", f"{fv:.1f}"))
d = np.array(diffs)
print(f"frames compared={len(d)} max_abs_diff={d.max():.3f} mean={d.mean():.3f} "
      f"text_mismatch={sum(1 for o in out if o[3] != o[4])}")
print("final fractional parts unique:", np.unique(np.round(col[~np.isnan(col)] % 1, 3))[:10])
for o in out[::40][:12]:
    print("frame=%d preview=%.3f final=%.3f text preview=%s final=%s" % o)
