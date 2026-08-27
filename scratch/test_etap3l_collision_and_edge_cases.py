import sys
from datetime import datetime, timedelta
from pathlib import Path

repo_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(repo_root))

def calc_gap_limit_reference(timestamps):
    if not timestamps or len(timestamps) <= 2:
        return None
    deltas = [
        (right - left).total_seconds()
        for left, right in zip(timestamps, timestamps[1:])
        if (right - left).total_seconds() > 0
    ]
    return max(5.0, sorted(deltas)[len(deltas) // 2] * 3.0) if deltas else None

_OLD_CACHE = {}
def old_get_gap_limit(timestamps):
    if not timestamps or len(timestamps) <= 2:
        return None
    k = (len(timestamps), timestamps[0], timestamps[-1])
    if k in _OLD_CACHE:
        return _OLD_CACHE[k]
    res = calc_gap_limit_reference(timestamps)
    _OLD_CACHE[k] = res
    return res

_HARDENED_CACHE = {}
def hardened_get_gap_limit(timestamps):
    if not timestamps or len(timestamps) <= 2:
        return None
    # Attribute on object if supported, else key by id + length + endpoints
    if hasattr(timestamps, "_gap_limit"):
        return timestamps._gap_limit
    k = (id(timestamps), len(timestamps), timestamps[0], timestamps[-1])
    if k in _HARDENED_CACHE:
        return _HARDENED_CACHE[k]
    res = calc_gap_limit_reference(timestamps)
    if len(_HARDENED_CACHE) >= 128:
        _HARDENED_CACHE.clear()
    _HARDENED_CACHE[k] = res
    return res

print("=" * 90)
print("PHASE 2: COLLISION TEST (SYNTHETIC TIMELINES A & B)")
print("=" * 90)

base_dt = datetime(2026, 8, 27, 12, 0, 0)
# Timeline A: 100 timestamps, mostly 1s deltas, ending with a jump to 500s
# Total duration = 500s, len = 100
ts_A = [base_dt + timedelta(seconds=i) for i in range(99)] + [base_dt + timedelta(seconds=500)]

# Timeline B: 100 timestamps, mostly 5s deltas, with smaller jumps
# Total duration = 500s, len = 100, same start, same end
ts_B = [base_dt] + [base_dt + timedelta(seconds=5 * i + 5) for i in range(99)]

ref_A = calc_gap_limit_reference(ts_A)
ref_B = calc_gap_limit_reference(ts_B)

print(f"Timeline A reference gap_limit: {ref_A:.3f} s (median delta: 1.0s -> gap_limit 5.0s)")
print(f"Timeline B reference gap_limit: {ref_B:.3f} s (median delta: 5.0s -> gap_limit 15.0s)")

# Old cache test
_OLD_CACHE.clear()
old_A = old_get_gap_limit(ts_A)
old_B = old_get_gap_limit(ts_B)
print(f"\nOld cache results: A = {old_A}, B = {old_B}")
if old_A == old_B and ref_A != ref_B:
    print(">>> OLD CACHE COLLISION CONFIRMED: B incorrectly received A's cached value!")
else:
    print("Old cache did not collide.")

# Hardened cache test
_HARDENED_CACHE.clear()
hard_A = hardened_get_gap_limit(ts_A)
hard_B = hardened_get_gap_limit(ts_B)
print(f"\nHardened cache results: A = {hard_A}, B = {hard_B}")
assert hard_A == ref_A, f"Hardened A mismatch: {hard_A} != {ref_A}"
assert hard_B == ref_B, f"Hardened B mismatch: {hard_B} != {ref_B}"
print(">>> HARDENED CACHE TEST: PASS (A and B correctly differentiated and 100% exact!)")

print("\n" + "=" * 90)
print("PHASE 3: EDGE CASE SUITE")
print("=" * 90)

edge_cases = {
    "0 timestamps": [],
    "1 timestamp": [base_dt],
    "2 timestamps": [base_dt, base_dt + timedelta(seconds=1)],
    "3 timestamps regular": [base_dt, base_dt + timedelta(seconds=1), base_dt + timedelta(seconds=2)],
    "Single large gap": [base_dt, base_dt + timedelta(seconds=1), base_dt + timedelta(seconds=100), base_dt + timedelta(seconds=101)],
    "Many gaps": [base_dt + timedelta(seconds=i*10) for i in range(10)],
    "Duplicate timestamps (0 delta)": [base_dt, base_dt, base_dt + timedelta(seconds=1), base_dt + timedelta(seconds=1)],
    "Non-positive backwards delta": [base_dt + timedelta(seconds=10), base_dt + timedelta(seconds=5), base_dt + timedelta(seconds=20)],
    "Irregular FIT cadence": [base_dt + timedelta(seconds=s) for s in [0, 1.1, 2.3, 3.4, 4.8, 12.0, 13.1, 14.2]],
}

for name, ts_list in edge_cases.items():
    ref_val = calc_gap_limit_reference(ts_list)
    hard_val = hardened_get_gap_limit(ts_list)
    assert ref_val == hard_val, f"Edge case '{name}' mismatch: ref={ref_val}, hard={hard_val}"
    print(f"  Edge case '{name:<32}': ref={str(ref_val):<8} | hard={str(hard_val):<8} -> PASS")

print("\nALL EDGE CASES PASSED WITH 100% PARITY!")
