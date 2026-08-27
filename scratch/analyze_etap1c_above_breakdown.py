import json
from pathlib import Path

profile_json = Path("scratch/etap1c_test/full1131_mode_c_combined.mp4.amd_profile.json")
with open(profile_json, "r", encoding="utf-8") as f:
    data = json.load(f)

print("=== TIMING SUMMARY FROM PROFILE JSON (1131 frames 4K) ===")
summary = data.get("stage_summaries", {})
for k, v in summary.items():
    print(f"  {k:32}: avg={v.get('avg_ms', 0):8.3f} ms | median={v.get('median_ms', 0):8.3f} ms | p95={v.get('p95_ms', 0):8.3f} ms")

print("\n=== WALL SUMMARY ===")
wall = data.get("etap8p_a_wall_summary", {})
for k, v in wall.items():
    print(f"  {k:32}: {v}")
