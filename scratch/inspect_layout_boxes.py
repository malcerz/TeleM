import sys, json
from pathlib import Path
_root = Path(__file__).resolve().parent.parent
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

from src.gui.layout_manager import normalize_layout

layout = normalize_layout("def_layout.json", 1920, 1080)
print("=== ENABLED INDICATORS IN def_layout.json ===")
for k, v in layout["indicators"].items():
    if v and v.get("enabled", True):
        form = v.get("form", "text")
        x = v.get("x", 0.0)
        y = v.get("y", 0.0)
        sz = v.get("size", v.get("font_size", 10.0))
        rot = v.get("rotation", 0)
        print(f"{k:20s}: form={form:12s} x={x:5.1f}% y={y:5.1f}% size={sz} rot={rot}")

print("\nCustom texts:")
for ct in layout.get("custom_texts", []):
    if ct.get("enabled", True):
        print(" ", ct)
