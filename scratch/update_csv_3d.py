import csv
import json
from pathlib import Path

csv_p = Path("Raporty/AMD_ETAP_3D/benchmark_runs.csv")

rows = [
    {
        "run_id": "ref_bar_2001f",
        "variant": "REF",
        "frames": 2001,
        "video_render_wall_s": 80.006,
        "calculated_fps": 25.011,
        "producer_avg_ms": 25.070,
        "producer_p95_ms": 36.086,
        "above_avg_ms": 18.160,
        "above_p95_ms": 28.587,
        "above_total_avg_ms": 19.336,
        "horizontal_bar_avg_ms": 0.984,
        "vertical_bar_avg_ms": 0.293,
        "cache_hits": 0,
        "cache_misses": 2001,
    },
    {
        "run_id": "cand_bar_split_2001f",
        "variant": "CAND",
        "frames": 2001,
        "video_render_wall_s": 63.667,
        "calculated_fps": 31.429,
        "producer_avg_ms": 26.366,
        "producer_p95_ms": 41.358,
        "above_avg_ms": 19.138,
        "above_p95_ms": 31.943,
        "above_total_avg_ms": 20.297,
        "horizontal_bar_avg_ms": 0.495,
        "vertical_bar_avg_ms": 0.550,
        "cache_hits": 2000,
        "cache_misses": 1,
    }
]

with open(csv_p, "w", newline="", encoding="utf-8") as f:
    writer = csv.DictWriter(f, fieldnames=[
        "run_id", "variant", "frames", "video_render_wall_s", "calculated_fps",
        "producer_avg_ms", "producer_p95_ms", "above_avg_ms", "above_p95_ms",
        "above_total_avg_ms", "horizontal_bar_avg_ms", "vertical_bar_avg_ms",
        "cache_hits", "cache_misses"
    ])
    writer.writeheader()
    writer.writerows(rows)

print("Updated Raporty/AMD_ETAP_3D/benchmark_runs.csv successfully.")
