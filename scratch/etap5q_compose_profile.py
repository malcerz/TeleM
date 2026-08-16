"""ETAP 5Q — extract per-widget compose breakdown from overlay profile."""
import json

d = json.load(open(r"Raporty/AMD_ETAP5G/l5q_profile.mp4.amd_profile.json", encoding="utf-8"))
p = d.get("etap5a", {})
print(f"enabled={p.get('enabled')} frames={p.get('frames')}")
metrics = p.get("metrics", {})

# per-widget totals
widget_totals = {}
for k, m in metrics.items():
    if k.startswith("indicator.") and k.endswith(".total"):
        name = k[len("indicator."):-len(".total")]
        widget_totals[name] = m
print("\n=== PER-WIDGET TOTAL (median / p95 / p99 / avg) ===")
for name, m in sorted(widget_totals.items(), key=lambda kv: -kv[1]["median_ms"]):
    print(f"  {name:34s} med={m['median_ms']:7.3f} p95={m['p95_ms']:7.3f} "
          f"p99={m['p99_ms']:7.3f} avg={m['avg_ms']:7.3f} calls/f={m['avg_calls_per_frame']:.2f}")

# per-widget breakdown of the TOP 5 by total
top5 = sorted(widget_totals.items(), key=lambda kv: -kv[1]["median_ms"])[:5]
for name, _ in top5:
    print(f"\n=== {name} — Pillow ops breakdown ===")
    prefix = f"indicator.{name}."
    sub = {}
    for k, m in metrics.items():
        if k.startswith(prefix) and not k.endswith(".total"):
            sub[k[len(prefix):]] = m
    for k, m in sorted(sub.items(), key=lambda kv: -kv[1]["median_ms"]):
        print(f"    {k:44s} med={m['median_ms']:7.3f} p95={m['p95_ms']:7.3f} "
              f"avg={m['avg_ms']:7.3f} calls/f={m['avg_calls_per_frame']:.2f}")

# global pillow ops
print("\n=== GLOBAL PILLOW OPS ===")
for k, m in sorted(metrics.items(), key=lambda kv: -kv[1]["median_ms"]):
    if k.startswith("pillow.") or k in ("graph.dynamic_labels", "graph.current_cursor",
                                        "graph.background_and_chart_composite", "map.crop_resize"):
        print(f"  {k:44s} med={m['median_ms']:7.3f} p95={m['p95_ms']:7.3f} avg={m['avg_ms']:7.3f}")

# value hit-rates for iso/exposure/temp/battery across frames (from extra_indicators? not in profile)
# We'll approximate value-change rate later; here just report the profile.
