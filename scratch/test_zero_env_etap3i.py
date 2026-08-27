import os
import sys
import subprocess
from pathlib import Path

repo_root = Path(__file__).resolve().parents[1]

# 1. Zero env test (no AMD_LEAN_GPU set)
cmd1 = [
    "python", "-c",
    "import os; "
    "from src.ffmpeg.amd_native_exporter import _env_flag; "
    "print('ZERO_ENV_DEFAULT:', _env_flag('AMD_LEAN_GPU', True))"
]
p1 = subprocess.run(cmd1, capture_output=True, text=True, cwd=str(repo_root), env={k: v for k, v in os.environ.items() if k != "AMD_LEAN_GPU"})
print("1. Zero Env (unset):", p1.stdout.strip())
assert "ZERO_ENV_DEFAULT: True" in p1.stdout

# 2. Explicit 0 test (AMD_LEAN_GPU=0)
cmd2 = [
    "python", "-c",
    "import os; "
    "os.environ['AMD_LEAN_GPU'] = '0'; "
    "from src.ffmpeg.amd_native_exporter import _env_flag; "
    "print('EXPLICIT_0:', _env_flag('AMD_LEAN_GPU', True))"
]
p2 = subprocess.run(cmd2, capture_output=True, text=True, cwd=str(repo_root))
print("2. Explicit 0 (fallback):", p2.stdout.strip())
assert "EXPLICIT_0: False" in p2.stdout

print("\nZERO-ENV AND FALLBACK TEST: 100% PASS!")
