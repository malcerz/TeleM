"""
Micro-prototype to verify GIL release and measure CPU-GPU thread overlap.
Compares:
1. Serial execution: CPU prep N -> GPU wait N -> CPU prep N+1 -> GPU wait N+1
2. Producer-Consumer Pipeline: Producer prepares N+1 in background while Consumer waits on GPU N
"""
import time
import queue
import threading
from pathlib import Path
import ctypes

def simulate_gpu_wait(ms: float):
    # Simulates blocking C++ call that releases GIL
    # We can load telem_amd_native.dll or use kernel32.Sleep
    kernel32 = ctypes.windll.kernel32
    kernel32.Sleep(int(ms))

def simulate_cpu_prep(ms: float):
    # Simulates CPU-heavy work (Pillow/Telemetry) holding GIL
    t0 = time.perf_counter()
    target_s = ms / 1000.0
    x = 0
    while (time.perf_counter() - t0) < target_s:
        x = (x * 31 + 17) & 0xFFFFFFFF
    return x

def run_serial_test(num_frames=50, cpu_ms=6.0, gpu_ms=16.0):
    t0 = time.perf_counter()
    for i in range(num_frames):
        simulate_cpu_prep(cpu_ms)
        simulate_gpu_wait(gpu_ms)
    total_s = time.perf_counter() - t0
    fps = num_frames / total_s
    return total_s, fps

def run_pipelined_test(num_frames=50, cpu_ms=6.0, gpu_ms=16.0):
    q = queue.Queue(maxsize=2)
    stop_event = threading.Event()
    
    def producer():
        for i in range(num_frames):
            if stop_event.is_set():
                break
            prep_data = simulate_cpu_prep(cpu_ms)
            q.put((i, prep_data))
        q.put(None) # Sentinel
        
    t_prod = threading.Thread(target=producer)
    
    t0 = time.perf_counter()
    t_prod.start()
    
    consumed = 0
    while True:
        item = q.get()
        if item is None:
            break
        frame_idx, data = item
        # Consumer does small non-preparable work (e.g. 1ms) + GPU wait (16ms)
        simulate_gpu_wait(gpu_ms)
        consumed += 1
        
    t_prod.join()
    total_s = time.perf_counter() - t0
    fps = consumed / total_s
    return total_s, fps

def main():
    print("=========================================================")
    print("       ETAP 8T-A ASYNC PIPELINE MICRO-PROTOTYPE          ")
    print("=========================================================\n")
    
    N = 60
    cpu_work_ms = 6.0
    gpu_work_ms = 16.0
    
    print(f"Testing {N} frames with CPU Prep = {cpu_work_ms} ms, GPU Wait = {gpu_work_ms} ms...")
    
    s_time, s_fps = run_serial_test(N, cpu_work_ms, gpu_work_ms)
    print(f"  SERIAL EXECUTION:    Total Time = {s_time:.3f} s, Throughput = {s_fps:.2f} FPS")
    
    p_time, p_fps = run_pipelined_test(N, cpu_work_ms, gpu_work_ms)
    print(f"  PIPELINED EXECUTION: Total Time = {p_time:.3f} s, Throughput = {p_fps:.2f} FPS")
    
    speedup = (p_fps - s_fps) / s_fps * 100.0
    time_saved = s_time - p_time
    print(f"\n  --> PIPELINE SPEEDUP: +{speedup:.1f}% throughput gain (Saved {time_saved:.3f} s)")
    print(f"  --> GIL OVERLAP PROOF: {'PASS' if p_fps > s_fps * 1.25 else 'FAIL'}")

if __name__ == "__main__":
    main()
