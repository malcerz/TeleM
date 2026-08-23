import json
from pathlib import Path

profile_path = Path("scratch/benchmark_etap10o_amd.mp4.amd_profile.json")
with open(profile_path, "r", encoding="utf-8") as f:
    data = json.load(f)

if "etap5a" in data:
    print("=== ETAP5A METRICS ===")
    print("Top keys in etap5a:", list(data["etap5a"].keys()))
    if "indicators" in data["etap5a"]:
        print("\nIndicator Metrics in etap5a:")
        for k, v in sorted(data["etap5a"]["indicators"].items()):
            print(f"  {k:<35}: {v}")
    if "timings" in data["etap5a"]:
        print("\nTimings in etap5a:")
        for k, v in sorted(data["etap5a"]["timings"].items()):
            print(f"  {k:<35}: {v}")
