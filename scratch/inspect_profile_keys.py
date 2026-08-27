"""Inspect available timing keys in existing profiles."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AUDIT_DIR = ROOT / "Raporty" / "AMD_RENDER_PATH_AUDIT"

p = AUDIT_DIR / "account_4k_full_300f.mp4.amd_profile.json"
if not p.exists():
    p = AUDIT_DIR / "test_B_4k_full.mp4.amd_profile.json"

with open(p) as f:
    profile = json.load(f)

print(f"Profile keys: {list(profile.keys())}")
timings = profile.get("timings", {})
print(f"\nAll timing keys ({len(timings)}):")
for k in sorted(timings.keys()):
    v = timings[k]
    avg = v.get("avg_ms", 0)
    med = v.get("median_ms", 0)
    p95 = v.get("p95_ms", 0)
    print(f"  {k}: avg={avg:.3f}ms  med={med:.3f}ms  p95={p95:.3f}ms")

# Check overlay profiler data separately
print("\netap8p_a:", json.dumps(profile.get("etap8p_a", {}), indent=2))
print("\nframe_accounting:", json.dumps(profile.get("frame_accounting", {}), indent=2))

# Check if overlay_profile data is embedded
op = profile.get("overlay_profile")
if op:
    print("\noverlay_profile metrics:", list(op.get("metrics", {}).keys())[:30])
