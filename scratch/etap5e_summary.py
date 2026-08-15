"""ETAP 5E — summarize BEFORE/AFTER compositing JSONs."""
import json
import sys

b = json.load(open("Raporty/AMD_ETAP5E/compositing_before.json", encoding="utf-8"))
a = json.load(open("Raporty/AMD_ETAP5E/compositing_after.json", encoding="utf-8"))

print("=== compose_overlay ms (in-process, profiled) ===")
print("BEFORE", json.dumps(b["compose_overlay_ms"]))
print("AFTER ", json.dumps(a["compose_overlay_ms"]))


def per_widget(j):
    out = {}
    for k, v in j["profiler"]["metrics"].items():
        if k.startswith("indicator.") and k.endswith(".paste_composite"):
            w = k.split(".")[1]
            out[w] = v
    return out


def ops(j, name):
    m = j["profiler"]["metrics"].get(name)
    if not m:
        return None
    return {
        "avg_ms": m["avg_ms"], "calls_per_frame": m["avg_calls_per_frame"],
        "avg_px_per_frame": m.get("avg_pixels_per_frame", 0),
    }


B = per_widget(b)
A = per_widget(a)
print("\n=== per-widget paste_composite avg / median / p95 (ms) ===")
print(f"{'widget':26s} {'BEFORE':>22s} {'AFTER':>22s} {'save(avg)':>10s}")
tot_b = tot_a = 0.0
for w in sorted(B):
    bb, aa = B[w], A.get(w)
    if aa is None:
        continue
    tot_b += bb["avg_ms"]
    tot_a += aa["avg_ms"]
    print(
        f"{w:26s} {bb['avg_ms']:7.3f}/{bb['median_ms']:6.3f}/{bb['p95_ms']:6.3f} "
        f"{aa['avg_ms']:7.3f}/{aa['median_ms']:6.3f}/{aa['p95_ms']:6.3f} "
        f"{bb['avg_ms']-aa['avg_ms']:10.3f}"
    )
print(f"{'TOTAL':26s} {tot_b:22.3f} {tot_a:22.3f} {tot_b-tot_a:10.3f}")

print("\n=== Pillow operation counters (per frame) ===")
for name in ("pillow.alpha_composite", "pillow.paste", "pillow.crop", "pillow.copy", "pillow.Image.new"):
    bo, ao = ops(b, name), ops(a, name)
    print(f"{name:24s} BEFORE {json.dumps(bo)}")
    print(f"{'':24s} AFTER  {json.dumps(ao)}")

print("\n=== regional clear ===")
for j, tag in ((b, "BEFORE"), (a, "AFTER")):
    m = j["profiler"]["metrics"].get("canvas.regional_clear")
    print(tag, json.dumps({k: m[k] for k in ("avg_ms", "median_ms", "p95_ms", "p99_ms", "avg_calls_per_frame")} if m else "n/a"))
