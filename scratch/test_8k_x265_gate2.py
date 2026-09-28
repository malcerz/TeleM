import os
import sys
import time
import subprocess
import threading
from ctypes import cdll, c_wchar_p, c_uint, c_void_p, byref, c_uint64, c_double, wintypes, create_string_buffer

os.environ["AMD_NATIVE_ENCODER_MODE"] = "x265"
if hasattr(os, "add_dll_directory"):
    os.add_dll_directory(r"C:\tools\mingw64\bin")
    os.add_dll_directory(os.path.abspath("native/d3d11_amf_pipeline/bin"))

input_8k = r"F:\GoPro\2026-09-22\GX020310.mp4"
output_mp4 = "scratch/test_8k_gate2_out.mp4"
NUM_FRAMES = int(os.environ.get("AMD_TEST_FRAMES", "10"))
READBACK_ONLY = os.environ.get("AMD_READBACK_ONLY", "0") == "1"
PLANE_READBACK = os.environ.get("AMD_8K_PLANE_READBACK", "0") == "1"
PLANE_GATE = os.environ.get("AMD_8K_PLANE_GATE", "FULL")
DISCARD_SINK = READBACK_ONLY and PLANE_READBACK and PLANE_GATE in ("Y_ONLY", "UV_ONLY")
PIX_FMT_IN = "p010le" if PLANE_READBACK else "nv12"

if os.path.exists(output_mp4):
    try: os.remove(output_mp4)
    except: pass

pipe_name = r"\\.\pipe\telem_x265_gate2_" + str(os.getpid())
pipe_path = pipe_name + ".h265"

import ctypes
kernel32 = ctypes.windll.kernel32
PIPE_ACCESS_INBOUND = 0x00000001
PIPE_TYPE_BYTE = 0x00000000
PIPE_READMODE_BYTE = 0x00000000
PIPE_WAIT = 0x00000000

h_pipe = kernel32.CreateNamedPipeW(
    pipe_path,
    PIPE_ACCESS_INBOUND,
    PIPE_TYPE_BYTE | PIPE_READMODE_BYTE | PIPE_WAIT,
    1,
    4 * 1024 * 1024,
    4 * 1024 * 1024,
    0,
    None
)

if READBACK_ONLY:
    cmd_ffmpeg = [
        "ffmpeg", "-v", "error",
        "-f", "rawvideo", "-pix_fmt", PIX_FMT_IN, "-s", "7680x4320",
        "-r", "30000/1001", "-i", "-", "-frames:v", str(NUM_FRAMES),
        "-f", "null", "-",
    ]
else:
    cmd_ffmpeg = [
        "ffmpeg", "-y",
        "-f", "rawvideo",
        "-pix_fmt", PIX_FMT_IN,
        "-s", "7680x4320",
        "-r", "30000/1001",
        "-i", "-",
        "-frames:v", str(NUM_FRAMES),
        "-c:v", "libx265",
        "-preset", "ultrafast",
        "-pix_fmt", "yuv420p10le",
        output_mp4
    ]

proc = subprocess.Popen(["cmd", "/c", "exit", "0"] if DISCARD_SINK else cmd_ffmpeg,
                        stdin=subprocess.PIPE if not DISCARD_SINK else subprocess.DEVNULL,
                        stderr=subprocess.PIPE)

def pump_pipe():
    kernel32.ConnectNamedPipe(h_pipe, None)
    buf = create_string_buffer(4 * 1024 * 1024)
    read_bytes = wintypes.DWORD()
    while True:
        res = kernel32.ReadFile(h_pipe, buf, len(buf), byref(read_bytes), None)
        if not res or read_bytes.value == 0:
            break
        if not DISCARD_SINK:
            try:
                proc.stdin.write(buf.raw[:read_bytes.value])
            except:
                break
    try:
        if not DISCARD_SINK:
            proc.stdin.close()
    except:
        pass
    kernel32.CloseHandle(h_pipe)

pump_t = threading.Thread(target=pump_pipe, daemon=True)
pump_t.start()

dll_path = os.path.abspath("native/d3d11_amf_pipeline/bin/telem_amd_native.dll")
dll = cdll.LoadLibrary(dll_path)
dll.telem_amd_create.restype = c_void_p
dll.telem_amd_create.argtypes = [c_wchar_p, c_wchar_p, c_uint, c_uint, c_uint, c_uint]
dll.telem_amd_read_video_sample.restype = c_uint
dll.telem_amd_read_video_sample.argtypes = [
    c_void_p, c_void_p, c_void_p, c_void_p, c_void_p,
    c_void_p, c_void_p, c_void_p, c_void_p, c_void_p
]
dll.telem_amd_set_decode_mode.argtypes = [c_void_p, c_uint]
dll.telem_amd_set_hud_enabled.argtypes = [c_void_p, c_uint]
dll.telem_amd_process_frame.argtypes = [c_void_p, c_uint, c_uint]
dll.telem_amd_process_frame.restype = c_uint
dll.telem_amd_flush.argtypes = [c_void_p]
dll.telem_amd_flush.restype = c_uint
dll.telem_amd_close.argtypes = [c_void_p]
dll.telem_amd_close.restype = c_uint
dll.telem_amd_get_readback_stats.argtypes = [c_void_p, c_void_p, c_void_p, c_void_p]

ctx = dll.telem_amd_create(input_8k, pipe_name, 7680, 4320, 30000, 1001)
if not ctx:
    print("telem_amd_create FAILED!", flush=True)
    sys.exit(1)

dll.telem_amd_set_decode_mode(ctx, 1) # D3D11VA
dll.telem_amd_set_hud_enabled(ctx, 0) # HUD OFF

decode_times = []
process_times = []
readback_times = []
process_ok = []

f_idx = c_uint64()
ts = c_uint64()
dur = c_uint64()
flags = c_uint()
dxgi_fmt = c_uint()
w = c_uint()
h = c_uint()
sub = c_uint()
tex_ptr = c_uint64()

t_global_start = time.perf_counter()

for f in range(NUM_FRAMES):
    t0 = time.perf_counter()
    ok_read = dll.telem_amd_read_video_sample(
        ctx, byref(f_idx), byref(ts), byref(dur), byref(flags),
        byref(dxgi_fmt), byref(w), byref(h), byref(sub), byref(tex_ptr)
    )
    t_decode = (time.perf_counter() - t0) * 1000.0
    decode_times.append(t_decode)

    t1 = time.perf_counter()
    ok_proc = dll.telem_amd_process_frame(ctx, f, 0)
    process_ok.append(bool(ok_proc))
    t_proc = (time.perf_counter() - t1) * 1000.0
    process_times.append(t_proc)

    last_ms = c_double()
    tot_frames = c_uint64()
    bytes_per_f = c_uint64()
    dll.telem_amd_get_readback_stats(ctx, byref(last_ms), byref(tot_frames), byref(bytes_per_f))
    readback_times.append(last_ms.value)

print(f"Frames processed: {NUM_FRAMES}. Flushing...", flush=True)
t_flush0 = time.perf_counter()
ok_flush = bool(dll.telem_amd_flush(ctx))
t_flush = (time.perf_counter() - t_flush0) * 1000.0

dll.telem_amd_close(ctx)
pump_t.join(timeout=10.0)

t_ffmpeg0 = time.perf_counter()
stdout, stderr = proc.communicate(timeout=120.0)
t_global_end = time.perf_counter()

total_wall_s = t_global_end - t_global_start
total_fps = NUM_FRAMES / total_wall_s

mean_decode = sum(decode_times) / len(decode_times)
mean_process = sum(process_times) / len(process_times)
mean_readback = sum(readback_times) / len(readback_times)
frame_mb = 7680 * 4320 * 1.5 / (1024.0 * 1024.0)
gbps = (frame_mb / 1024.0) / (mean_readback / 1000.0) if mean_readback > 0 else 0.0

print(f"=== GATE 2 (10 FRAMES 8K HUD OFF CPU X265) RESULTS ===")
print(f"DECODE_MS={mean_decode:.2f}")
print(f"GPU_PROCESS_MS={mean_process:.2f}")
print(f"READBACK_MS={mean_readback:.2f}")
print(f"READBACK_MB_PER_FRAME={frame_mb:.2f}")
print(f"READBACK_GBPS={gbps:.2f}")
print(f"FLUSH_MS={t_flush:.2f}")
print(f"TOTAL_WALL_S={total_wall_s:.2f}")
print(f"TOTAL_FPS={total_fps:.3f}")
print(f"READBACK_ONLY={READBACK_ONLY}")
print(f"PLANE_READBACK={PLANE_READBACK}")
print(f"PLANE_GATE={PLANE_GATE}")
print(f"OUTPUT_SIZE_BYTES={os.path.getsize(output_mp4) if os.path.exists(output_mp4) else 0}")
print(f"FFMPEG_RETURNCODE={proc.returncode}")
print(f"PROCESS_OK_ALL={all(process_ok)}")
print(f"FLUSH_OK={ok_flush}")

if (all(process_ok) and ok_flush and proc.returncode == 0 and
        (READBACK_ONLY or (os.path.exists(output_mp4) and os.path.getsize(output_mp4) > 0))):
    print("GATE 2: PASS")
else:
    print("GATE 2: FAIL")
