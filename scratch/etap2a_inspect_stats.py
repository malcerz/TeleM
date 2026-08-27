"""Inspect ETAP 2A smoke profile JSONs for gauge-related stats."""
import json
from pathlib import Path

BASE = Path(r"c:\_DEV\TeleM\scratch\etap2a_test")

for name in ("etap2a_cand_short.mp4.amd_profile.json", "etap2a_ref_short.mp4.amd_profile.json"):
    p = BASE / name
    d = json.loads(p.read_text(encoding="utf-8"))
    print("=" * 30, name)
    for k, v in d.items():
        if "gauge" in k.lower():
            print(f"  {k} = {v}")
    # per-frame records?
    ft = d.get("frame_timings") or d.get("frames") or []
    if ft and isinstance(ft, list):
        rec = ft[min(300, len(ft) - 1)]
        gauge_keys = [k for k in rec.keys() if "gauge" in k.lower()] if isinstance(rec, dict) else []
        print("  per-frame record keys w/ gauge:", gauge_keys)
        for k in gauge_keys:
            vals = [f.get(k) for f in ft[:400] if isinstance(f, dict) and k in f]
            nz = [x for x in vals if x]
            print(f"    {k}: n={len(vals)} nonzero={len(nz)} sample={nz[:3]}")
