"""Inspect raw GPMF JSON keys and sample counts."""
import json
from pathlib import Path

root = Path("c:/_DEV/TeleM")

def inspect_gpmf(json_path: Path):
    print(f"\n=======================================================")
    print(f"INSPECTING: {json_path.name}")
    print(f"=======================================================")
    data = json.load(open(json_path, encoding="utf-8"))
    
    # Check structure
    if isinstance(data, list):
        print(f"Root is list of {len(data)} items")
        records = data
    elif isinstance(data, dict):
        print(f"Root is dict with keys: {list(data.keys())}")
        records = [data]
    else:
        print("Unknown root type")
        return
        
    # Search for ISO, SHUT, TMPC, GPS9, etc.
    found_keys = {}
    
    def search_keys(obj, path=""):
        if isinstance(obj, dict):
            for k, v in obj.items():
                new_path = f"{path}.{k}" if path else k
                if k in ("ISO", "ISOR", "SHUT", "TMPC", "GPS9", "GPS5", "ACCL", "GYRO", "streams"):
                    count = len(v.get("samples", [])) if isinstance(v, dict) and "samples" in v else (len(v) if isinstance(v, list) else 1)
                    found_keys[new_path] = count
                search_keys(v, new_path)
        elif isinstance(obj, list):
            for i, item in enumerate(obj[:5]):
                search_keys(item, f"{path}[{i}]")
                
    search_keys(data)
    for k, count in found_keys.items():
        print(f"  {k}: count/samples={count}")

if __name__ == "__main__":
    inspect_gpmf(root / "Video" / "GX030120.json")
    inspect_gpmf(root / "Video" / "GX020079.json")
