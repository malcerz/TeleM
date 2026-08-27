import csv
from pathlib import Path

csv_p = Path("Raporty/AMD_ETAP_3E/benchmark_runs.csv")

rows = [
    {
        "run_id": "ref_single_union_2001f",
        "variant": "REF",
        "frames": 2001,
        "render_wall_s": 140.295,
        "calculated_fps": 14.263,
        "producer_avg_ms": 47.604,
        "producer_p95_ms": 60.206,
        "above_compose_avg_ms": 19.088,
        "above_crop_ms": 4.318,
        "above_tobytes_ms": 9.003,
        "above_upload_ms": 1.961,
        "rects_avg": 1.0,
        "rects_p95": 1.0,
        "bytes_avg": 21765120.0,
        "bytes_p95": 21765120.0,
        "consumer_upload_ms": 3.189,
        "consumer_native_ms": 6.339,
        "pipeline_total_ms": 10.662,
    },
    {
        "run_id": "cand_multi_rect_2001f",
        "variant": "CAND",
        "frames": 2001,
        "render_wall_s": 62.278,
        "calculated_fps": 32.130,
        "producer_avg_ms": 25.782,
        "producer_p95_ms": 37.465,
        "above_compose_avg_ms": 18.822,
        "above_crop_ms": 0.939,
        "above_tobytes_ms": 1.105,
        "above_upload_ms": 0.473,
        "rects_avg": 4.0,
        "rects_p95": 4.0,
        "bytes_avg": 2640612.0,
        "bytes_p95": 2640612.0,
        "consumer_upload_ms": 1.240,
        "consumer_native_ms": 2.416,
        "pipeline_total_ms": 4.753,
    }
]

with open(csv_p, "w", newline="", encoding="utf-8") as f:
    writer = csv.DictWriter(f, fieldnames=[
        "run_id", "variant", "frames", "render_wall_s", "calculated_fps",
        "producer_avg_ms", "producer_p95_ms", "above_compose_avg_ms",
        "above_crop_ms", "above_tobytes_ms", "above_upload_ms",
        "rects_avg", "rects_p95", "bytes_avg", "bytes_p95",
        "consumer_upload_ms", "consumer_native_ms", "pipeline_total_ms"
    ])
    writer.writeheader()
    writer.writerows(rows)

print("Updated benchmark_runs.csv successfully.")
