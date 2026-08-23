import json
from pathlib import Path

profile_path = Path("scratch/benchmark_etap10o_amd.mp4.amd_profile.json")
with open(profile_path, "r", encoding="utf-8") as f:
    data = json.load(f)

for key in ["frame_accounting", "etap8p_a", "etap5a", "etap5n", "timings"]:
    if key in data:
        print(f"\n=== {key} ===")
        print(json.dumps(data[key], indent=2))
