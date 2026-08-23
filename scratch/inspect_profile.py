import json
from pathlib import Path

profile_path = Path("scratch/benchmark_etap10o_amd.mp4.amd_profile.json")
with open(profile_path, "r", encoding="utf-8") as f:
    data = json.load(f)

print("Top keys in JSON profile:", list(data.keys()))
if "stages" in data:
    print("\nStages:")
    for k, v in data["stages"].items():
        print(f"  {k:<35}: avg {v.get('avg_ms', 0):.3f} ms | med {v.get('median_ms', 0):.3f} ms | p95 {v.get('p95_ms', 0):.3f} ms")

if "indicators" in data:
    print("\nIndicators:")
    for k, v in data["indicators"].items():
        print(f"  {k:<35}: {v}")

if "overlay" in data:
    print("\nOverlay keys:", list(data["overlay"].keys()))
