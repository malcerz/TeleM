"""CPU P0.4 stage 4: cost of the FFmpeg RGBA -> yuva420p10le + overlay stage.

The HUD is the real golden pre-compression frame (looped single RGBA frame via
-stream_loop, so no Python transport cost); base is the real GX010370 4K HLG decode.

Usage: bench_overlay.py <graph> --sink null|ultrafast --frames N [--dump K] --out-dir D --tag T
Graphs are named in GRAPHS below.  --dump K also writes the first K output frames
as raw yuv420p10le (for bit-exact comparison between graphs).
"""
import argparse
import json
import os
import re
import subprocess
import threading
import time

import psutil

FF = r"C:\_DEV\SportCamHUD\runtime\common\ffmpeg\ffmpeg.exe"
VIDEO = r"D:\GoPro\GX010370.MP4"
HUD = r"C:\_DEV\SportCamHUD\Raporty\CPU_P04_GUI_GOLDEN_OVERLAY\golden_run\export_hud_f150.rgba"
START = 900
OV = "[base][ov]overlay=0:0:shortest=1:format=yuv420p10[v]"
PRE = "[0:v]null[base];"
CONV = "scale=in_range=full:out_range=full:out_color_matrix=bt2020:flags={fl}{thr},format=yuva420p10le"
GRAPHS = {
    "decode_only": None,
    "current": PRE + "[1:v]setpts=PTS-STARTPTS[ov];" + OV,
    "explicit_format": PRE + "[1:v]setpts=PTS-STARTPTS,format=yuva420p10le[ov];" + OV,
}
for n in (2, 4, 8, 16):
    GRAPHS[f"scale_threads{n}"] = PRE + "[1:v]setpts=PTS-STARTPTS," + CONV.format(fl="bicubic", thr=f":threads={n}") + "[ov];" + OV
GRAPHS["conv_only_t1"] = "[1:v]setpts=PTS-STARTPTS," + CONV.format(fl="bicubic", thr=":threads=1") + "[v]"
GRAPHS["conv_only_t4"] = "[1:v]setpts=PTS-STARTPTS," + CONV.format(fl="bicubic", thr=":threads=4") + "[v]"
GRAPHS["overlay_only_preconverted"] = PRE + "[1:v]setpts=PTS-STARTPTS[ov];" + OV
HUD_YUVA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "overlay", "hud.yuva10")
GRAPHS["scale_threads1"] = PRE + "[1:v]setpts=PTS-STARTPTS," + CONV.format(fl="bicubic", thr=":threads=1") + "[ov];" + OV


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("graph")
    ap.add_argument("--sink", default="null", choices=["null", "ultrafast"])
    ap.add_argument("--frames", type=int, default=150)
    ap.add_argument("--dump", type=int, default=0)
    ap.add_argument("--extra-filter-args", default="")
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--tag", default="")
    a = ap.parse_args()
    os.makedirs(a.out_dir, exist_ok=True)
    tag = a.tag or f"{a.graph}_{a.sink}_{a.frames}"
    ss = f"{START * 1001 / 30000:.9f}"
    cmd = [FF, "-y", "-hide_banner", "-loglevel", "info", "-nostats", "-progress", "pipe:1"]
    if a.extra_filter_args:
        cmd += a.extra_filter_args.split()
    cmd += ["-noautorotate", "-ss", ss, "-i", VIDEO]
    g = GRAPHS[a.graph]
    if g is None:
        mapv = "0:v:0"
    else:
        pre = a.graph == "overlay_only_preconverted"
        cmd += ["-stream_loop", "-1", "-f", "rawvideo", "-pix_fmt", "yuva420p10le" if pre else "rgba",
                "-s", "3840x2160", "-framerate", "30000/1001", "-i", HUD_YUVA if pre else HUD,
                "-filter_complex", g]
        mapv = "[v]"
    if a.dump:  # dump mode: only K raw frames for bit-exact comparison between graphs (no timing sink)
        cmd += ["-map", mapv, "-frames:v", str(a.dump), "-pix_fmt", "yuv420p10le", "-f", "rawvideo",
                os.path.join(a.out_dir, tag + ".yuv")]
    else:
        cmd += ["-map", mapv, "-frames:v", str(a.frames)]
        if a.sink == "ultrafast":
            cmd += ["-c:v", "libx265", "-preset", "ultrafast", "-b:v", "16000k", "-profile:v", "main10",
                    "-pix_fmt", "yuv420p10le", "-an", os.path.join(a.out_dir, tag + ".mp4")]
        else:
            cmd += ["-pix_fmt", "yuv420p10le", "-f", "null", "-"]
    t0 = time.perf_counter()
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, bufsize=0)
    ps = psutil.Process(p.pid)
    prog, err, samples = [], [], []
    stop = threading.Event()

    def sampler():
        last = None
        while not stop.is_set():
            try:
                ct = ps.cpu_times()
                c = ct.user + ct.system
                now = time.perf_counter()
                if last:
                    samples.append((now - t0, (c - last[0]) / (now - last[1])))
                last = (c, now)
            except psutil.Error:
                break
            time.sleep(0.25)

    def rd_out():
        buf = b""
        while chunk := p.stdout.read(4096):
            buf += chunk
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                m = re.match(rb"frame=(\d+)", line.strip())
                if m:
                    prog.append((time.perf_counter() - t0, int(m.group(1))))

    def rd_err():
        for raw in iter(p.stderr.readline, b""):
            err.append(raw.decode("utf-8", "replace").rstrip())

    for fn in (sampler, rd_out, rd_err):
        threading.Thread(target=fn, daemon=True).start()
    rc = p.wait()
    wall = time.perf_counter() - t0
    stop.set()
    time.sleep(0.3)
    cpu_total = None
    try:
        pass
    except Exception:
        pass
    res = {"graph": a.graph, "sink": a.sink, "frames": a.frames, "rc": rc, "wall_s": round(wall, 3),
           "wall_fps": round(a.frames / wall, 2), "cmd": " ".join(cmd)}
    if prog:
        n = max(f for _, f in prog)
        pts = [(t, f) for t, f in prog if n * 0.1 <= f <= n * 0.9]
        if len(pts) >= 2 and pts[-1][0] > pts[0][0]:
            res["steady_fps_10_90"] = round((pts[-1][1] - pts[0][1]) / (pts[-1][0] - pts[0][0]), 2)
    if samples:
        mid = [s for s in samples if s[0] > 0.8] or samples
        res["ffmpeg_cores_avg"] = round(sum(s[1] for s in mid) / len(mid), 2)
        res["cpu_core_s_per_frame"] = round(res["ffmpeg_cores_avg"] * wall / a.frames, 4)
    for line in err:
        m = re.search(r"encoded (\d+) frames in ([\d.]+)s \(([\d.]+) fps\), ([\d.]+) kb/s", line)
        if m:
            res["x265_fps"], res["x265_kbps"] = float(m[3]), float(m[4])
        if "auto_scale" in line and "->" in line:
            res["auto_scale"] = line.split("] ", 1)[-1][:200]
    res["errors"] = [l for l in err if "error" in l.lower() or "Invalid" in l][-3:]
    json.dump(res, open(os.path.join(a.out_dir, tag + ".json"), "w"), indent=1)
    print(json.dumps({k: v for k, v in res.items() if k != "cmd"}))


if __name__ == "__main__":
    main()
