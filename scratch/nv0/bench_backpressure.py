"""bench_shm_backpressure.py
Measures SHM/pipe/backpressure in a production-like run.
Instruments:
- HUD dimensions and RGBA bytes/frame
- workers, SHM slots, MAX_IN_FLIGHT
- SHM slot acquire wait
- queue put wait (pipe_queue.put)
- stdin.write duration
Determines: does producer wait on FFmpeg, or FFmpeg wait on producer?
"""
import sys, time, statistics, json, os, threading, queue
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BASE_DIR))

# Instrumented versions of key functions
_acquire_waits = []
_queue_put_waits = []
_write_durations = []

# Monkey-patch SharedFramePool.acquire to measure wait time
from src.ffmpeg import shared_memory as shm_mod

_original_acquire = shm_mod.SharedFramePool.acquire

def _patched_acquire(self, timeout=30.0):
    t0 = time.perf_counter()
    result = _original_acquire(self, timeout=timeout)
    t1 = time.perf_counter()
    _acquire_waits.append((t1 - t0) * 1000)
    return result

shm_mod.SharedFramePool.acquire = _patched_acquire

# Monkey-patch _pipe_writer_thread stdin.write to measure write time
# We do this by patching the ffmpeg_write timer in streaming
from src.ffmpeg import streaming as streaming_mod

_original_pipe_writer = streaming_mod._pipe_writer_thread

def _patched_pipe_writer(write_queue, stdin_buffer, done_event, shm_pool=None):
    """Instrumented pipe writer: measure queue.get wait and stdin.write time."""
    try:
        while True:
            t_get0 = time.perf_counter()
            try:
                item = write_queue.get(timeout=0.5)
                t_get1 = time.perf_counter()
            except queue.Empty:
                if done_event.is_set():
                    break
                continue
            _queue_put_waits.append((t_get1 - t_get0) * 1000)  # time writer waited for item
            if item is None:
                break
            t_w0 = time.perf_counter()
            try:
                if isinstance(item, tuple):
                    slot, memview = item
                    try:
                        stdin_buffer.write(memview)
                    finally:
                        try:
                            memview.release()
                        except Exception:
                            pass
                    if shm_pool is not None:
                        shm_pool.release(slot)
                else:
                    stdin_buffer.write(item)
            finally:
                t_w1 = time.perf_counter()
                _write_durations.append((t_w1 - t_w0) * 1000)
    except (BrokenPipeError, OSError):
        pass

streaming_mod._pipe_writer_thread = _patched_pipe_writer

# Also patch queue.put in main thread by wrapping pipe_queue put
_original_queue_class = queue.Queue
_put_waits_producer = []

# We'll wrap put calls in stream_overlay_to_ffmpeg by patching Queue
class InstrumentedQueue(_original_queue_class):
    def put(self, item, block=True, timeout=None):
        t0 = time.perf_counter()
        result = super().put(item, block=block, timeout=timeout)
        t1 = time.perf_counter()
        _put_waits_producer.append((t1 - t0) * 1000)
        return result

# Patch queue.Queue in streaming module
streaming_mod.queue.Queue = InstrumentedQueue

# Now run the actual export
import subprocess, shutil as sh
from src.ffmpeg.worker_cache import init_worker
from src.ffmpeg.streaming import stream_overlay_to_ffmpeg

VIDEO_PATH = BASE_DIR / "Video" / "GX020079.MP4"
OUTPUT_PATH = BASE_DIR / "Raporty" / "NVIDIA_NV0" / "nv0_backpressure_test.mp4"
TARGET_FRAMES = 1131

ffprobe = sh.which("ffprobe")
probe_cmd = [ffprobe, "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=duration,avg_frame_rate",
             "-of", "json", str(VIDEO_PATH)]
result = subprocess.run(probe_cmd, capture_output=True, text=True)
info = json.loads(result.stdout)
stream = info["streams"][0]
duration_s = float(stream["duration"])
num, den = map(int, stream["avg_frame_rate"].split("/"))
fps = num / den

try:
    from src.gui.qt.controller import AppController
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    controller = AppController()
    layout = controller.layout
    print(f"[INFO] Layout loaded: {len(layout.get('indicators', {}))} indicators")
except Exception as e:
    print(f"[WARN] AppController failed ({e}), using empty layout")
    layout = {"indicators": {}, "custom_texts": []}

ffmpeg = sh.which("ffmpeg") or sh.which("ffmpeg.EXE")

print("=== BACKPRESSURE MEASUREMENT RUN ===")
print(f"HUD size: 3840x2160 RGBA = {3840*2160*4/1024/1024:.1f} MiB/frame")
print(f"Frames: {TARGET_FRAMES}")
print()

t0 = time.perf_counter()
total_piped = stream_overlay_to_ffmpeg(
    ffmpeg_exe=ffmpeg,
    input_files=str(VIDEO_PATH),
    output_file=str(OUTPUT_PATH),
    duration_s=duration_s,
    start_dt_utc=None,
    tz_offset_hours=0,
    speed_samples=[],
    track_samples=[],
    alt_samples=[],
    font_path="",
    layout=layout,
    field_samples={},
    max_distance_m=None,
    target_fps=fps,
    render_w=3840,
    render_h=2160,
    resolution_name="source",
    rotation_degrees=0,
    container_rotation=0,
    overlay_w=3840,
    overlay_h=2160,
    progress_cb=None,
    on_render_progress=None,
    cancel_event=None,
    active_process_holder=None,
)
t1 = time.perf_counter()
wall = t1 - t0
true_fps = total_piped / wall if wall > 0 else 0.0

print()
print(f"=== BACKPRESSURE RESULTS ===")
print(f"Total piped: {total_piped}  Wall: {wall:.2f}s  TRUE FPS: {true_fps:.2f}")
print()

def stats(times, name):
    if not times:
        print(f"  {name}: NO DATA")
        return {}
    s = sorted(times)
    n = len(s)
    med = statistics.median(s)
    p95 = s[int(n * 0.95)]
    p99 = s[int(n * 0.99)]
    avg = statistics.mean(s)
    mx = max(s)
    print(f"  {name:40s}  n={n:4d}  avg={avg:7.2f}ms  median={med:7.2f}ms  P95={p95:7.2f}ms  P99={p99:7.2f}ms  max={mx:7.2f}ms")
    return {"n": n, "avg": avg, "median": med, "p95": p95, "p99": p99, "max": mx}

print("Timing breakdown:")
acq = stats(_acquire_waits, "SHM slot acquire wait (main→free)")
put = stats(_put_waits_producer, "pipe_queue.put wait (producer→writer)")
deq = stats(_queue_put_waits, "Writer queue.get wait (writer←producer)")
wrt = stats(_write_durations, "stdin.write duration (writer→FFmpeg)")

# Throughput
mib_per_frame = 3840 * 2160 * 4 / 1024 / 1024
if _write_durations:
    avg_write_ms = statistics.mean(_write_durations)
    mib_per_s = mib_per_frame / (avg_write_ms / 1000) if avg_write_ms > 0 else 0
    print(f"\n  Pipe throughput: {mib_per_frame:.1f} MiB/frame @ avg {avg_write_ms:.1f}ms/write = {mib_per_s:.0f} MiB/s")

# Backpressure verdict
print()
print("=== BACKPRESSURE VERDICT ===")
avg_acq = statistics.mean(_acquire_waits) if _acquire_waits else 0
avg_wrt = statistics.mean(_write_durations) if _write_durations else 0
avg_put = statistics.mean(_put_waits_producer) if _put_waits_producer else 0

if avg_acq > 5.0:
    print(f"A. PRODUCER WAITS ON FFMPEG: avg SHM acquire = {avg_acq:.1f}ms >> SHM slots full → FFmpeg slow")
elif avg_put > 5.0:
    print(f"A/B: queue.put wait = {avg_put:.1f}ms → pipe_queue full → writer slow → FFmpeg slow or backpressure present")
elif avg_wrt > 10.0:
    print(f"B. FFMPEG WAITS ON PRODUCER: stdin.write = {avg_wrt:.1f}ms slow → producer is the bottleneck")
else:
    print(f"C. NO SIGNIFICANT BACKPRESSURE: acq={avg_acq:.1f}ms put={avg_put:.1f}ms write={avg_wrt:.1f}ms")

result = {
    "hud_dimensions": "3840x2160",
    "rgba_bytes_per_frame": 3840 * 2160 * 4,
    "mib_per_frame": mib_per_frame,
    "total_piped": total_piped,
    "wall_s": wall,
    "true_fps": true_fps,
    "shm_acquire_wait": acq,
    "queue_put_wait_producer": put,
    "writer_dequeue_wait": deq,
    "stdin_write_duration": wrt,
}

report_dir = BASE_DIR / "Raporty" / "NVIDIA_NV0"
with open(report_dir / "bench_backpressure.json", "w") as f:
    json.dump(result, f, indent=2)
print(f"\nResults saved to Raporty/NVIDIA_NV0/bench_backpressure.json")
