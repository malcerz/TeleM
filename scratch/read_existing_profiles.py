"""Read existing audit profiles to extract per-widget ABOVE timings."""
import json
import statistics
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT3 = ROOT / "Raporty" / "AMD_RENDER_PATH_AUDIT_3"
OUT3.mkdir(parents=True, exist_ok=True)

AUDIT_DIR = ROOT / "Raporty" / "AMD_RENDER_PATH_AUDIT"

# Find best available 4K full profile
candidates_4k = list(AUDIT_DIR.glob("account_4k_full*.amd_profile.json"))
candidates_4k += list(AUDIT_DIR.glob("*4k*full*.amd_profile.json"))
candidates_4k += list(AUDIT_DIR.glob("*audit3_above_4k*.amd_profile.json"))
# Also check OUT3
candidates_4k += list((ROOT / "Raporty" / "AMD_RENDER_PATH_AUDIT_3").glob("*.amd_profile.json"))

print("4K candidate profiles:", [p.name for p in candidates_4k])

# Find best available 1080p full profile
candidates_1080 = list(AUDIT_DIR.glob("account_4k_full*.amd_profile.json"))
candidates_1080 = [p for p in AUDIT_DIR.glob("*.amd_profile.json") if "1080" in p.name]
candidates_1080 += [p for p in AUDIT_DIR.glob("*.amd_profile.json") if "full" in p.name]

print("1080p candidate profiles:", [p.name for p in candidates_1080][:5])

# Read the best profile available
def read_profile_timings(path):
    with open(path) as f:
        profile = json.load(f)
    return profile

# Check what indicator-level timings are available
for p in (candidates_4k + candidates_1080)[:6]:
    if not p.exists():
        continue
    try:
        profile = read_profile_timings(p)
        timings = profile.get("timings", {})
        ind_keys = [k for k in timings if "indicator." in k and ".render" in k]
        if ind_keys:
            print(f"\n=== {p.name} has {len(ind_keys)} indicator render timings ===")
            for k in sorted(ind_keys)[:30]:
                v = timings[k]
                avg = v.get("avg_ms", 0)
                med = v.get("median_ms", 0)
                p95 = v.get("p95_ms", 0)
                print(f"  {k}: avg={avg:.3f}ms  med={med:.3f}ms  p95={p95:.3f}ms")
            # also above_compose
            for k in ["above_compose", "above_region_to_bytes", "above_total"]:
                if k in timings:
                    v = timings[k]
                    print(f"  [ABOVE] {k}: avg={v.get('avg_ms',0):.3f}ms  med={v.get('median_ms',0):.3f}ms  p95={v.get('p95_ms',0):.3f}ms")
    except Exception as e:
        print(f"  Error reading {p.name}: {e}")
