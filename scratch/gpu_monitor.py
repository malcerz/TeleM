import sys, os, time, subprocess, threading
from pathlib import Path
_root = Path(__file__).resolve().parent.parent
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

import psutil

class GPUMonitor:
    def __init__(self, interval=0.1):
        self.interval = interval
        self.running = False
        self.samples = []
        self._thread = None

    def _sample_loop(self):
        while self.running:
            try:
                # Query nvidia-smi
                res = subprocess.run(
                    ["nvidia-smi", "--query-gpu=utilization.gpu,utilization.decoder,utilization.encoder,utilization.memory,memory.used", "--format=csv,noheader,nounits"],
                    capture_output=True, text=True, timeout=1.0
                )
                if res.returncode == 0:
                    parts = [int(x.strip()) for x in res.stdout.strip().split(",")]
                    cpu_p = psutil.cpu_percent(interval=None)
                    self.samples.append({
                        "gpu": parts[0],
                        "nvdec": parts[1],
                        "nvenc": parts[2],
                        "mem_util": parts[3],
                        "vram_mb": parts[4],
                        "cpu": cpu_p
                    })
            except Exception:
                pass
            time.sleep(self.interval)

    def start(self):
        self.samples = []
        self.running = True
        self._thread = threading.Thread(target=self._sample_loop, daemon=True)
        self._thread.start()

    def stop(self):
        self.running = False
        if self._thread:
            self._thread.join(timeout=2.0)

    def get_stats(self):
        if not self.samples:
            return {"gpu": 0, "nvdec": 0, "nvenc": 0, "cpu": 0, "vram_mb": 0}
        # filter out empty samples at boundaries
        s = self.samples
        return {
            "gpu_avg": sum(x["gpu"] for x in s) / len(s),
            "gpu_max": max(x["gpu"] for x in s),
            "nvdec_avg": sum(x["nvdec"] for x in s) / len(s),
            "nvdec_max": max(x["nvdec"] for x in s),
            "nvenc_avg": sum(x["nvenc"] for x in s) / len(s),
            "nvenc_max": max(x["nvenc"] for x in s),
            "cpu_avg": sum(x["cpu"] for x in s) / len(s),
            "cpu_max": max(x["cpu"] for x in s),
            "vram_mb": max(x["vram_mb"] for x in s),
        }

print("GPUMonitor initialized successfully.")
