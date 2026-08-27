import json
import os
import sys
import time
from pathlib import Path

repo_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(repo_root))

from scratch.run_etap3e_benchmarks import run_single_benchmark

print("=" * 90)
print("PHASE 2 & 3: DIRECT GPU TIMESTAMP PROBE (LEAN GPU OFF vs ON)")
print("=" * 90)

# Run with GPU timestamps enabled
os.environ["AMD_GPU_TIMESTAMP_PROFILE"] = "1"
os.environ["AMD_NATIVE_DIAGNOSTICS"] = "0"
os.environ["AMD_ABOVE_MULTI_RECT"] = "1"
os.environ["AMD_ABOVE_FINE_DIRTY"] = "0"

# 1. Run REF (AMD_LEAN_GPU=0) 300 frames
os.environ["AMD_LEAN_GPU"] = "0"
row_ref, prof_ref = run_single_benchmark("gpu_ts_ref_300f", "REF_CPU_LEAN", 1, 300)

# 2. Run CAND (AMD_LEAN_GPU=1) 300 frames
os.environ["AMD_LEAN_GPU"] = "1"
row_cand, prof_cand = run_single_benchmark("gpu_ts_cand_300f", "CAND_GPU_LEAN", 1, 300)

print("\nFinished GPU timestamp probe runs.")
