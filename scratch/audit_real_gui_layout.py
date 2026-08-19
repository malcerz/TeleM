"""Audit of the actual layout used by the GUI and investigating ETAP 8L issues."""
import hashlib
import json
from pathlib import Path

root = Path("c:/_DEV/TeleM")
layout_path = root / "def_layout.json"

def audit_layout():
    raw_bytes = layout_path.read_bytes()
    sha256 = hashlib.sha256(raw_bytes).hexdigest()
    print(f"=== LAYOUT FILE: {layout_path} ===")
    print(f"SHA256: {sha256}")
    
    data = json.loads(raw_bytes.decode("utf-8"))
    indicators = data.get("indicators", {})
    print(f"Total indicators in layout: {len(indicators)}")
    
    # Check ordering relative to track_map
    map_key = "track_map"
    
    print("\n--- ALL INDICATORS IN INSERTION ORDER ---")
    below_map = []
    map_ind = None
    above_map = []
    
    seen_map = False
    for idx, (name, ind) in enumerate(indicators.items()):
        field = ind.get("field")
        form = ind.get("form")
        source = ind.get("source")
        x = ind.get("x")
        y = ind.get("y")
        size = ind.get("size")
        enabled = ind.get("enabled", True)
        
        status = "ENABLED" if enabled else "DISABLED"
        print(f"[{idx:2d}] {name:30s} | field={str(field):20s} | form={str(form):10s} | source={str(source):8s} | x={x}, y={y} | size={size} | {status}")
        
        if name == map_key:
            seen_map = True
            if enabled:
                map_ind = (name, ind)
        else:
            if enabled:
                if not seen_map:
                    below_map.append((name, ind))
                else:
                    above_map.append((name, ind))

    print("\n=======================================================")
    print("--- ORDERED MAP LAYOUT PARTS (ENABLED ONLY) ---")
    print("=======================================================")
    print(f"\nBELOW_MAP count: {len(below_map)}")
    for name, ind in below_map:
        print(f"  BELOW: {name:30s} x={ind.get('x')} y={ind.get('y')} form={ind.get('form')} label='{ind.get('label')}'")
        
    print(f"\nMAP: {map_ind[0] if map_ind else 'NONE'}")
    if map_ind:
        print(f"  MAP details: {json.dumps(map_ind[1], indent=2)}")
        
    print(f"\nABOVE_MAP count: {len(above_map)}")
    for name, ind in above_map:
        print(f"  ABOVE: {name:30s} x={ind.get('x')} y={ind.get('y')} form={ind.get('form')} label='{ind.get('label')}' source={ind.get('source')}")

if __name__ == "__main__":
    audit_layout()
