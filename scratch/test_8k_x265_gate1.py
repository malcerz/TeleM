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
output_mp4 = "scratch/test_8k_gate1_out.mp4"

if os.path.exists(output_mp4):
    try: os.remove(output_mp4)
    except: pass

pipe_name = r"\\.\pipe\telem_x265_gate1_" + str(os.getpid())
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

cmd_ffmpeg = [
    "ffmpeg", "-y",
    "-f", "rawvideo",
    "-pix_fmt", "nv12",
    "-s", "7680x4320",
    "-r", "30000/1001",
    "-i", "-",
    "-frames:v", "1",
    "-c:v", "libx265",
    "-preset", "fast",
    "-pix_fmt", "yuv420p10le",
    output_mp4
]

proc = subprocess.Popen(cmd_ffmpeg, stdin=subprocess.PIPE, stderr=subprocess.PIPE)

def pump_pipe():
    kernel32.ConnectNamedPipe(h_pipe, None)
    buf = create_string_buffer(4 * 1024 * 1024)
    read_bytes = wintypes.DWORD()
    while True:
        res = kernel32.ReadFile(h_pipe, buf, len(buf), byref(read_bytes), None)
        if not res or read_bytes.value == 0:
            break
        try:
            proc.stdin.write(buf.raw[:read_bytes.value])
        except:
            break
    try:
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

print("Initializing telem_amd_create for 8K -> 8K x265...", flush=True)
ctx = dll.telem_amd_create(input_8k, pipe_name, 7680, 4320, 30000, 1001)
if not ctx:
    print("telem_amd_create FAILED!", flush=True)
    sys.exit(1)

dll.telem_amd_set_decode_mode(ctx, 1) # D3D11VA
dll.telem_amd_set_hud_enabled(ctx, 0) # HUD OFF

f_idx = c_uint64()
ts = c_uint64()
dur = c_uint64()
flags = c_uint()
dxgi_fmt = c_uint()
w = c_uint()
h = c_uint()
sub = c_uint()
tex_ptr = c_uint64()

print("Reading 1 frame from 8K input...", flush=True)
t0 = time.perf_counter()
ok_read = dll.telem_amd_read_video_sample(
    ctx, byref(f_idx), byref(ts), byref(dur), byref(flags),
    byref(dxgi_fmt), byref(w), byref(h), byref(sub), byref(tex_ptr)
)
t_read = time.perf_counter() - t0
print(f"Sample read: ok={ok_read}, fmt={dxgi_fmt.value}, {w.value}x{h.value}, elapsed={t_read*1000:.2f}ms", flush=True)

print("Processing frame 0 (8K GPU conversion + staging readback)...", flush=True)
t1 = time.perf_counter()
ok_proc = dll.telem_amd_process_frame(ctx, 0, 0)
t_proc = time.perf_counter() - t1
print(f"Process frame 0: ok={ok_proc}, elapsed={t_proc*1000:.2f}ms", flush=True)

print("Flushing encoder (draining pipeline)...", flush=True)
t2 = time.perf_counter()
dll.telem_amd_flush(ctx)
t_flush = time.perf_counter() - t2
print(f"Flush completed: elapsed={t_flush*1000:.2f}ms", flush=True)

last_ms = c_double()
tot_frames = c_uint64()
bytes_per_f = c_uint64()
dll.telem_amd_get_readback_stats(ctx, byref(last_ms), byref(tot_frames), byref(bytes_per_f))
print(f"READBACK STATS: last_readback_ms={last_ms.value:.2f}ms, frames={tot_frames.value}, bytes={bytes_per_f.value}", flush=True)

dll.telem_amd_close(ctx)
pump_t.join(timeout=10.0)
stdout, stderr = proc.communicate(timeout=60.0)

print(f"FFmpeg exit code: {proc.returncode}", flush=True)
if proc.returncode != 0:
    print("FFmpeg stderr:", stderr.decode(errors="replace")[-500:], flush=True)

if os.path.exists(output_mp4) and os.path.getsize(output_mp4) > 0:
    print(f"Output MP4 exists: size={os.path.getsize(output_mp4)} bytes", flush=True)
    probe = subprocess.run([
        "ffprobe", "-v", "error", "-show_entries",
        "stream=width,height,pix_fmt,codec_name", "-of", "json", output_mp4
    ], capture_output=True, text=True)
    print("FFPROBE:", probe.stdout.strip(), flush=True)
    print("GATE 1: 8K CPU X265 1 FRAME = PASS")
else:
    print("GATE 1: 8K CPU X265 1 FRAME = FAIL")
