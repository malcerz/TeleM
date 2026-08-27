"""Compact ETAP 2A benchmark comparison: ref_full vs cand_full profiles."""
import json

KEYS = [
    "compose_overlay",
    "map_cpu_upload",
    "gauge_tobytes",
    "above_compose",
    "above_total",
    "above_region_to_bytes",
    "above_exact_crop",
    "above_tight_bbox_collect",
    "HUD dirty bbox",
    "PIL/buffer preparation",
    "update_hud",
]

profs = {}
for tag in ("ref", "cand"):
    with open(f"scratch/etap2a_test/etap2a_{tag}_full.mp4.amd_profile.json",
              encoding="utf-8") as fh:
        profs[tag] = json.load(fh)

for tag in ("ref", "cand"):
    d = profs[tag]
    print(f"== {tag}: true_fps={d.get('true_fps'):.3f} "
          f"wall={d.get('total_wall_clock_s')}s")

tref = profs["ref"]["timings"]
tcand = profs["cand"]["timings"]
print(f"{'metric':30s} {'ref_avg':>9s} {'cand_avg':>9s} {'delta':>9s}")
for k in KEYS:
    r = tref.get(k, {}).get("avg_ms", 0.0)
    c = tcand.get(k, {}).get("avg_ms", 0.0)
    print(f"{k:30s} {r:9.3f} {c:9.3f} {c - r:+9.3f}")

print("-- other deltas > 0.2 ms --")
for k in sorted(set(tref) | set(tcand)):
    r = tref.get(k, {}).get("avg_ms", 0.0)
    c = tcand.get(k, {}).get("avg_ms", 0.0)
    if abs(c - r) > 0.2 and k not in KEYS:
        print(f"{k:34s} ref={r:8.3f} cand={c:8.3f} delta={c - r:+8.3f}")
