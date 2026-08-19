"""
Benchmark runner for ETAP 8Q AFTER benchmarks:
- 3 x 1131 frames 4K with AMD_ABOVE_TEXT_CACHE=1
- 1 x 5395 frames 4K with AMD_ABOVE_TEXT_CACHE=1
"""
import os
import sys
import json
import time
from pathlib import Path

root = Path("c:/_DEV/TeleM")
sys.path.insert(0, str(root))
sys.path.insert(0, str(root / "src"))

from scratch.run_etap8p_b_benchmarks import run_single_benchmark, out_dir

def main():
    print("=== ETAP 8Q: RUNNING AFTER BENCHMARKS (AMD_ABOVE_TEXT_CACHE=1) ===")
    v_1131 = root / "Video" / "GX020079.mp4"
    fit_1131 = root / "Video" / "Morning_Ride.fit"
    
    os.environ["AMD_ABOVE_TEXT_CACHE"] = "1"
    os.environ["AMD_TELEMETRY_MODE"] = "PRECOMPUTED"
    
    results = {"after_1131": [], "full_5395": None}
    
    # 1. 3 x AFTER (1131 frames)
    for i in range(1, 4):
        res = run_single_benchmark(f"etap8q_after_run{i}", v_1131, fit_1131, "PRECOMPUTED", 1131)
        results["after_1131"].append(res)
        
    # 2. 1 x Full Material (5395 frames)
    v_5395 = root / "Video" / "GX030120.MP4"
    fit_5395 = root / "Video" / "Popoludniowa_jazda_na_rowerze_solar_battery.fit"
    print("\n--- RUNNING FULL 5395-FRAME EXPORT ---", flush=True)
    res_full = run_single_benchmark("etap8q_full_5395", v_5395, fit_5395, "PRECOMPUTED", 5395)
    results["full_5395"] = res_full
    
    summary_path = out_dir / "etap8q_after_benchmarks.json"
    with open(summary_path, "w") as f:
        json.dump(results, f, indent=2)
        
    print(f"\nAll ETAP 8Q AFTER benchmarks complete! Saved to {summary_path}")

if __name__ == "__main__":
    main()
