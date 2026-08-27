import time
from datetime import datetime, timedelta

timestamps = [datetime.fromtimestamp(1700000000 + i) for i in range(4300)]

t0 = time.perf_counter()
for _ in range(100):
    deltas = [
        (right - left).total_seconds()
        for left, right in zip(timestamps, timestamps[1:])
        if (right - left).total_seconds() > 0
    ]
    if deltas:
        gap_limit = max(5.0, sorted(deltas)[len(deltas) // 2] * 3.0)
t1 = time.perf_counter()

print(f"Time for 1 call: {(t1 - t0)*10.0:.3f} ms")
print(f"For 2 charts per frame: {(t1 - t0)*20.0:.3f} ms / frame!")
