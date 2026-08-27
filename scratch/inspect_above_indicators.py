import json
import os
import sys
from pathlib import Path

repo_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(repo_root))

from src.ffmpeg.amd_native_exporter import _ordered_map_layout_parts

layout = json.load(open(repo_root / "def_layout.json", encoding="utf-8"))
compose_layout, map_above_layout, map_after_keys = _ordered_map_layout_parts(layout)

print("--- BELOW MAP LAYOUT INDICATORS ---")
for k, v in (compose_layout.get("indicators", {}) if compose_layout else {}).items():
    print(f"  {k:<30}: enabled={v.get('enabled', True)}, form={v.get('form', 'text')}")

print("\n--- ABOVE MAP LAYOUT INDICATORS ---")
for k, v in (map_above_layout.get("indicators", {}) if map_above_layout else {}).items():
    print(f"  {k:<30}: enabled={v.get('enabled', True)}, form={v.get('form', 'text')}")
