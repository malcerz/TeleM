import json
from pathlib import Path

layout = json.load(open("def_layout.json", encoding="utf-8"))
inds = layout.get("indicators", {})

print("=" * 80)
print("INVENTORY OF ALL INDICATORS IN def_layout.json:")
print("=" * 80)

enabled_count = 0
for k, cfg in inds.items():
    enabled = cfg.get("enabled", False)
    form = cfg.get("form", "unknown")
    source = cfg.get("source", "unknown")
    x = cfg.get("x", 0.0)
    y = cfg.get("y", 0.0)
    size = cfg.get("size", cfg.get("font_size", 0.0))
    if enabled:
        enabled_count += 1
        print(f"[{enabled_count:2d}] {k:<30} form={form:<15} source={source:<10} x={x:<6} y={y:<6} size={size}")

print(f"\nTotal enabled indicators: {enabled_count}")
