"""
Diagnostic script for ETAP 8Q:
1. Run 3 x 1131-frame BEFORE baseline (AMD_ABOVE_TEXT_CACHE=0).
2. Detailed sub-timing of above_compose.
3. Indicator inventory.
"""
import os
import sys
import json
import time
from pathlib import Path

root = Path("c:/_DEV/TeleM")
sys.path.insert(0, str(root))
sys.path.insert(0, str(root / "src"))

from scratch.run_etap8p_b_benchmarks import run_single_benchmark, setup_telemetry, layout, out_dir

def main():
    print("=== ETAP 8Q: MEASURING FRESH CURRENT BEFORE BASELINE (3 x 1131 frames) ===")
    v_1131 = root / "Video" / "GX020079.mp4"
    fit_1131 = root / "Video" / "Morning_Ride.fit"
    
    os.environ["AMD_ABOVE_TEXT_CACHE"] = "0"
    os.environ["AMD_TELEMETRY_MODE"] = "PRECOMPUTED"
    
    results = []
    for i in range(1, 4):
        res = run_single_benchmark(f"etap8q_before_run{i}", v_1131, fit_1131, "PRECOMPUTED", 1131)
        results.append(res)
        
    summary_path = out_dir / "etap8q_before_baseline.json"
    with open(summary_path, "w") as f:
        json.dump(results, f, indent=2)
        
    print(f"\nFresh BEFORE baseline saved to {summary_path}")

if __name__ == "__main__":
    main()
