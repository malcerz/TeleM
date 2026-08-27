import os
import sys
from pathlib import Path

repo_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(repo_root))

from src.ffmpeg.amd_native_exporter import _resolve_above_multi_rect

print("=" * 90)
print("PHASE 18: POST-FLIP ZERO-ENV & EXPLICIT OVERRIDE VERIFICATION")
print("=" * 90)

# 1. Zero-Env Test (unset)
if "AMD_ABOVE_MULTI_RECT" in os.environ:
    del os.environ["AMD_ABOVE_MULTI_RECT"]

val_zero = _resolve_above_multi_rect()
print(f"Zero-env (unset) -> _resolve_above_multi_rect() = {val_zero}")
assert val_zero is True, "Expected True by default when unset!"

# 2. Explicit Override OFF (0)
os.environ["AMD_ABOVE_MULTI_RECT"] = "0"
val_off = _resolve_above_multi_rect()
print(f"Explicit AMD_ABOVE_MULTI_RECT=0 -> _resolve_above_multi_rect() = {val_off}")
assert val_off is False, "Expected False when explicitly set to 0!"

# 3. Explicit Override ON (1)
os.environ["AMD_ABOVE_MULTI_RECT"] = "1"
val_on = _resolve_above_multi_rect()
print(f"Explicit AMD_ABOVE_MULTI_RECT=1 -> _resolve_above_multi_rect() = {val_on}")
assert val_on is True, "Expected True when explicitly set to 1!"

print("\n  -> POST-FLIP ZERO-ENV & OVERRIDE TESTS: ALL PASS!")
