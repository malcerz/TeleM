import sys, os, time, subprocess
from pathlib import Path
_root = Path(__file__).resolve().parent.parent
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

from scratch.gpu_monitor import GPUMonitor

v_file = "Video/GX020079.mp4"
n_frames = 1132

def run_cmd_benchmark(name, cmd):
    print(f"\n--- Running pilot test: {name} ---")
    mon = GPUMonitor(interval=0.05)
    mon.start()
    t0 = time.perf_counter()
    res = subprocess.run(cmd, capture_output=True, text=True)
    t1 = time.perf_counter()
    mon.stop()
    elapsed = t1 - t0
    fps = n_frames / elapsed
    stats = mon.get_stats()
    print(f"[{name}] Return: {res.returncode} | Time: {elapsed:.3f} s | FPS: {fps:.1f}")
    print(f"Stats: NVDEC avg={stats.get('nvdec_avg',0):.1f}% max={stats.get('nvdec_max',0)}% | NVENC avg={stats.get('nvenc_avg',0):.1f}% max={stats.get('nvenc_max',0)}% | GPU avg={stats.get('gpu_avg',0):.1f}% | CPU avg={stats.get('cpu_avg',0):.1f}%")
    if res.returncode != 0:
        print(f"Stderr: {res.stderr[:500]}")
    return elapsed, fps, stats

# 1. Test A: NVDEC only
cmd_a = [
    "ffmpeg", "-y", "-hwaccel", "cuda", "-hwaccel_output_format", "cuda",
    "-i", v_file, "-f", "null", "-"
]
run_cmd_benchmark("TEST A: NVDEC ONLY", cmd_a)

# 2. Test B: NVDEC + TeleM conversion + NVENC
cmd_b = [
    "ffmpeg", "-y", "-hwaccel", "cuda", "-hwaccel_output_format", "cuda",
    "-i", v_file,
    "-filter_complex", "[0:v]scale_cuda=format=yuv420p[base];[base]null[vout]",
    "-map", "[vout]", "-map_metadata", "-1", "-metadata:s:v:0", "rotate=0",
    "-c:v", "hevc_nvenc", "-preset", "p1", "-tune", "hq", "-rc", "vbr",
    "-cq", "24", "-pix_fmt", "cuda", "-gpu", "0",
    "-b:v", "40M", "-maxrate", "40M", "-bufsize", "80M",
    "-f", "null", "-"
]
run_cmd_benchmark("TEST B: NVDEC + CONV + NVENC", cmd_b)

# 3. Test C1: NVDEC + CONV + 1x overlay_cuda no-op + NVENC
cmd_c1 = [
    "ffmpeg", "-y", "-hwaccel", "cuda", "-hwaccel_output_format", "cuda",
    "-i", v_file,
    "-f", "lavfi", "-i", "color=c=black@0.0:s=16x16:r=29.97",
    "-filter_complex", "[0:v]scale_cuda=format=yuv420p[base];[1:v]format=yuva420p,hwupload_cuda[ov];[base][ov]overlay_cuda=x=0:y=0[vout]",
    "-map", "[vout]", "-map_metadata", "-1", "-metadata:s:v:0", "rotate=0",
    "-c:v", "hevc_nvenc", "-preset", "p1", "-tune", "hq", "-rc", "vbr",
    "-cq", "24", "-pix_fmt", "cuda", "-gpu", "0",
    "-b:v", "40M", "-maxrate", "40M", "-bufsize", "80M",
    "-shortest", "-f", "null", "-"
]
run_cmd_benchmark("TEST C1: 1x overlay_cuda NO-OP", cmd_c1)

# 4. Test C2: NVDEC + CONV + 3-Region Atlas split/crop/scale/upload/3x overlay_cuda NO-OP
cmd_c2 = [
    "ffmpeg", "-y", "-hwaccel", "cuda", "-hwaccel_output_format", "cuda",
    "-i", v_file,
    "-f", "lavfi", "-i", "color=c=black@0.0:s=1112x668:r=29.97",
    "-filter_complex", (
        "[0:v]scale_cuda=format=yuv420p[base];"
        "[1:v]setpts=PTS-STARTPTS,format=rgba,split=3[ov_raw_0][ov_raw_1][ov_raw_2];"
        "[ov_raw_0]crop=426:170:0:0,scale=852:340:flags=bilinear,format=yuva420p,hwupload_cuda[ov_0];"
        "[ov_raw_1]crop=678:332:430:0,scale=1356:664:flags=bilinear,format=yuva420p,hwupload_cuda[ov_1];"
        "[ov_raw_2]crop=1082:332:0:336,scale=2164:664:flags=bilinear,format=yuva420p,hwupload_cuda[ov_2];"
        "[base][ov_0]overlay_cuda=x=20:y=28[v_step_0];"
        "[v_step_0][ov_1]overlay_cuda=x=2380:y=1496[v_step_1];"
        "[v_step_1][ov_2]overlay_cuda=x=88:y=1496[vout]"
    ),
    "-map", "[vout]", "-map_metadata", "-1", "-metadata:s:v:0", "rotate=0",
    "-c:v", "hevc_nvenc", "-preset", "p1", "-tune", "hq", "-rc", "vbr",
    "-cq", "24", "-pix_fmt", "cuda", "-gpu", "0",
    "-b:v", "40M", "-maxrate", "40M", "-bufsize", "80M",
    "-shortest", "-f", "null", "-"
]
run_cmd_benchmark("TEST C2: 3-REGION ATLAS CUDA FILTER GRAPH NO-OP", cmd_c2)

# 5. Test E: NVENC only (synthetic GPU frames)
cmd_e = [
    "ffmpeg", "-y",
    "-f", "lavfi", "-i", f"nullsrc=s=3840x2160:r=29.97:d=37.74",
    "-filter_complex", "[0:v]format=yuv420p,hwupload_cuda[vout]",
    "-map", "[vout]",
    "-c:v", "hevc_nvenc", "-preset", "p1", "-tune", "hq", "-rc", "vbr",
    "-cq", "24", "-pix_fmt", "cuda", "-gpu", "0",
    "-b:v", "40M", "-maxrate", "40M", "-bufsize", "80M",
    "-f", "null", "-"
]
run_cmd_benchmark("TEST E: NVENC ONLY (synthetic)", cmd_e)
