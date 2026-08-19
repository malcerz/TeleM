"""Inspect indicators in def_layout.json."""
import json
from pathlib import Path

root = Path("c:/_DEV/TeleM")
layout = json.load(open(root / "def_layout.json", encoding="utf-8"))

print("Top-level keys:", list(layout.keys()))
indicators = layout.get("indicators", {})
print(f"Total indicators: {len(indicators)}")
for k, v in indicators.items():
    print(f"  - {k}: enabled={v.get('enabled')}, source={v.get('source')}, field={v.get('field')}, form={v.get('form')}")
