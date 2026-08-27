import csv
import json
import os
import sys
import time
from pathlib import Path

repo_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(repo_root))

from scratch.run_etap3e_benchmarks import run_single_benchmark

OUT_DIR = repo_root / "Raporty" / "AMD_ETAP_3F"
OUT_DIR.mkdir(parents=True, exist_ok=True)
CSV_PATH = OUT_DIR / "benchmark_runs.csv"

def main():
    rows = []
    runs = [
        ("ref_1_1000f", "REF", 0, 1000),
        ("cand_1_1000f", "CAND", 1, 1000),
        ("ref_2_1000f", "REF", 0, 1000),
        ("cand_2_1000f", "CAND", 1, 1000),
        ("ref_3_1000f", "REF", 0, 1000),
        ("cand_3_1000f", "CAND", 1, 1000),
    ]

    for run_id, variant, multi_rect, frames in runs:
        row, prof = run_single_benchmark(run_id, variant, multi_rect, frames)
        rows.append(row)

    with open(CSV_PATH, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "run_id", "variant", "frames", "render_wall_s", "calculated_fps",
            "producer_avg_ms", "producer_p95_ms", "above_compose_avg_ms",
            "above_crop_ms", "above_tobytes_ms", "above_upload_ms",
            "rects_avg", "rects_p95", "bytes_avg", "bytes_p95",
            "consumer_upload_ms", "consumer_native_ms", "pipeline_total_ms"
        ])
        writer.writeheader()
        writer.writerows(rows)

    print(f"\nAll 6 alternating benchmark rows successfully written to {CSV_PATH}")

if __name__ == "__main__":
    main()
