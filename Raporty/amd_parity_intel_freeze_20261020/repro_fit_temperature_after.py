"""Rebuild the AMD render-prep columns for the user's night export with the
patched builder and compare FIT/GPMF temperature with the Preview resolver."""
import json, sys, time
from datetime import timedelta
from pathlib import Path
import numpy as np
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from telemetry_fit import parse_fit
from src.render_telemetry_cache import RenderTelemetryCache
from src.render_preparation import RenderPreparationService as RPS  # noqa
from src.telemetry_resolver import resolve_current_presentation

old_cache_dir, fit_path, frames = Path(sys.argv[1]), Path(sys.argv[2]), int(sys.argv[3])
old = RenderTelemetryCache.load(old_cache_dir / "manifest.json", mmap=True)
recs = parse_fit(fit_path)
fit = {k: v["samples"] for k, v in recs.field_catalog.items() if v.get("samples")}
layout = json.load(open(ROOT / "def_layout.json", encoding="utf-8"))
gp = np.asarray(old._col_temp, dtype=float)
base = old.base_dt
fps = old.fps
gpmf_temp = [(base + timedelta(seconds=i / fps), float(gp[i])) for i in range(0, old.frames, 30) if not np.isnan(gp[i])]
t0 = time.perf_counter()
cache = RPS.build_telemetry_cache_vectorized(
    layout=layout, base_dt=base, start_dt_utc=base, fit_data=fit,
    temperature_samples=gpmf_temp, total_frames=frames, target_fps=fps,
    cache_dir=Path(sys.argv[4]) if len(sys.argv) > 4 else None)
build_s = time.perf_counter() - t0
cfg = layout["indicators"]["fit_temperature_text"]
mism = 0; n = 0; maxd = 0.0
for i in range(0, frames, max(1, frames // 400)):
    dt = base + timedelta(seconds=round(i / fps * 1e6) / 1e6)
    pv = resolve_current_presentation(fit["temperature"], dt, "temperature", cfg, active_time_mapper=None)
    fv = cache.lookup(i)["extra_indicators"]["fit_temperature_text"][0]
    if pv is None or fv is None:
        continue
    n += 1; maxd = max(maxd, abs(pv - fv)); mism += f"{pv:.1f}" != f"{fv:.1f}"
col = np.asarray(cache.columns["fit_temperature_text"], dtype=float)
print(json.dumps({"frames": frames, "build_s": round(build_s, 2), "compared": n, "max_abs_diff": maxd,
                  "text_mismatch": mism,
                  "final_has_fraction": bool(np.any(np.abs(col[~np.isnan(col)] % 1) > 1e-6)),
                  "sample_final_text": [f"{col[i]:.1f}" for i in range(0, frames, frames // 8)]}, indent=1))
