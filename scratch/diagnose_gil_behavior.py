"""
Check GIL release across ctypes functions vs time.sleep vs native DLL.
"""
import os
import time
import queue
import threading
import ctypes
from pathlib import Path

root = Path("c:/_DEV/TeleM")
dll_path = root / "native" / "d3d11_amf_pipeline" / "bin" / "telem_amd_native.dll"

if hasattr(os, "add_dll_directory"):
    mingw_bin = r"c:\tools\mingw64\bin"
    if os.path.exists(mingw_bin):
        os.add_dll_directory(mingw_bin)

# Load telem_amd_native.dll
native_dll = ctypes.CDLL(str(dll_path))

def cpu_work(duration_ms):
    t0 = time.perf_counter()
    target = duration_ms / 1000.0
    x = 0
    while (time.perf_counter() - t0) < target:
        x = (x * 31 + 17) & 0xFFFFFFFF
    return x

def test_overlap(wait_fn):
    num_frames = 40
    q = queue.Queue(maxsize=2)
    
    t_start = time.perf_counter()
    
    def producer():
        for i in range(num_frames):
            data = cpu_work(8.0) # 8ms of pure CPU work holding GIL
            q.put((i, data))
        q.put(None)
        
    t_prod = threading.Thread(target=producer)
    t_prod.start()
    
    for _ in range(num_frames):
        item = q.get()
        if item is None: break
        wait_fn(16.0) # 16ms of wait
        
    t_prod.join()
    elapsed = time.perf_counter() - t_start
    return elapsed

# Serial baseline: 40 * (8 + 16) = 960 ms
t_serial_expected = 40 * 0.024 # 0.96s
# Full overlap: 40 * max(8, 16) = 640 ms

t1 = test_overlap(lambda ms: time.sleep(ms / 1000.0))
print(f"time.sleep overlap time: {t1:.3f} s (expected serial: {t_serial_expected:.3f}s, pipelined: 0.640s)")
