import time
from datetime import datetime

timestamps = [datetime.fromtimestamp(1700000000 + i) for i in range(4300)]
_GAP_LIMIT_CACHE = {}

def get_gap_limit(ts_tuple):
    # Cache key by identity / length / first-last timestamp
    k = (len(ts_tuple), ts_tuple[0], ts_tuple[-1])
    if k not in _GAP_LIMIT_CACHE:
        deltas = [
            (right - left).total_seconds()
            for left, right in zip(ts_tuple, ts_tuple[1:])
            if (right - left).total_seconds() > 0
        ]
        _GAP_LIMIT_CACHE[k] = max(5.0, sorted(deltas)[len(deltas) // 2] * 3.0) if deltas else None
    return _GAP_LIMIT_CACHE[k]

# Warmup
ts_t = tuple(timestamps)
get_gap_limit(ts_t)

t0 = time.perf_counter()
for _ in range(1000):
    g = get_gap_limit(ts_t)
t1 = time.perf_counter()

print(f"Time for 1000 cached calls: {(t1 - t0)*1000.0:.3f} ms ({(t1 - t0):.6f} ms / call)")
