"""CPU P0.6: libx265 tuning bench on the real 4K HLG decode + real HUD overlay graph.

Same graph as production (RGBA HUD -> auto_scale -> yuva420p10le -> overlay 10-bit), HUD frame looped
from the golden RGBA file, real GX010370 base (noautorotate, start frame 900), ABR rate control.
Reports wall/steady/x265 FPS, ffmpeg CPU cores + core-s/frame, RSS peak, real bitrate, first-frame and
finalisation time (from -progress timestamps), plus the x265 configuration lines.

Usage: bench_x265.py --preset faster [--x265 "frame-threads=3:no-wpp=1"] [--bitrate 16000]
                     [--frames 300] [--tag T] [--keep]
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
HUD = r"C:\Users\Malcerz\AppData\Local\Temp\claude\C---DEV-SportCamHUD\b4efa350-e454-46be-88bc-9f16c132caa0\scratchpad\hud_golden.rgba"
OUT = "C:/_DEV/SportCamHUD/Raporty/CPU_P06_X265_TUNING/sweeps"
GRAPH = ("[0:v]null[base];[1:v]setpts=PTS-STARTPTS[ov];"
         "[base][ov]overlay=0:0:shortest=1:format=yuv420p10[v]")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--preset", required=True)
    ap.add_argument("--x265", default="")
    ap.add_argument("--bitrate", type=int, default=16000)
    ap.add_argument("--crf", type=int, default=0)
    ap.add_argument("--frames", type=int, default=300)
    ap.add_argument("--tag", default="")
    ap.add_argument("--keep", action="store_true")
    a = ap.parse_args()
    os.makedirs(OUT, exist_ok=True)
    tag = a.tag or f"{a.preset}_{a.x265 or 'default'}".replace(":", "_").replace("=", "-")
    out = f"{OUT}/{tag}.mp4"
    cmd = [FF, "-y", "-hide_banner", "-loglevel", "info", "-nostats", "-progress", "pipe:1",
           "-noautorotate", "-ss", f"{900 * 1001 / 30000:.9f}", "-i", VIDEO,
           "-stream_loop", "-1", "-f", "rawvideo", "-pix_fmt", "rgba", "-s", "3840x2160",
           "-framerate", "30000/1001", "-i", HUD, "-filter_complex", GRAPH, "-map", "[v]",
           "-frames:v", str(a.frames), "-c:v", "libx265", "-preset", a.preset]
    if a.x265:
        cmd += ["-x265-params", a.x265]
    cmd += (["-crf", str(a.crf)] if a.crf else ["-b:v", f"{a.bitrate}k"])
    cmd += ["-profile:v", "main10", "-pix_fmt", "yuv420p10le", "-color_primaries", "bt2020",
            "-color_trc", "arib-std-b67", "-colorspace", "bt2020nc", "-color_range", "pc", "-an", out]
    t0 = time.perf_counter()
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, bufsize=0)
    ps = psutil.Process(p.pid)
    err, prog, samples, rss = [], [], [], [0]
    stop = threading.Event()

    def sampler():
        last = None
        while not stop.is_set():
            try:
                ct = ps.cpu_times()
                c = ct.user + ct.system
                now = time.perf_counter()
                rss[0] = max(rss[0], ps.memory_info().rss)
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
    res = {"tag": tag, "preset": a.preset, "x265_params": a.x265, "bitrate_kbps_target": a.bitrate,
           "frames": a.frames, "rc": rc, "wall_s": round(wall, 2), "wall_fps": round(a.frames / wall, 3)}
    if prog:
        n = max(f for _, f in prog)
        res["first_frame_s"] = round(next((t for t, f in prog if f >= 1), prog[0][0]), 2)
        pts = [(t, f) for t, f in prog if n * 0.1 <= f <= n * 0.9]
        if len(pts) >= 2 and pts[-1][0] > pts[0][0]:
            res["steady_fps"] = round((pts[-1][1] - pts[0][1]) / (pts[-1][0] - pts[0][0]), 3)
        res["finalize_s"] = round(wall - prog[-1][0], 2)
    mid = [s for s in samples if s[0] > 1.0] or samples
    if mid:
        res["cores_avg"] = round(sum(s[1] for s in mid) / len(mid), 2)
        res["cpu_util_pct_of_16"] = round(100 * res["cores_avg"] / (os.cpu_count() or 16), 1)
        res["core_s_per_frame"] = round(res["cores_avg"] * wall / a.frames, 3)
    res["rss_peak_mb"] = round(rss[0] / 2**20)
    for line in err:
        m = re.search(r"encoded (\d+) frames in ([\d.]+)s \(([\d.]+) fps\), ([\d.]+) kb/s", line)
        if m:
            res["x265_fps"], res["x265_kbps"] = float(m[3]), float(m[4])
        for key in ("frame threads", "Thread pool", "Lookahead", "Rate Control", "Slices", "Keyframe"):
            if key in line and "x265 [info]" in line:
                res.setdefault("x265_info", []).append(line.split("]:", 1)[-1].strip())
    if os.path.exists(out):
        res["bytes"] = os.path.getsize(out)
    res["errors"] = [l for l in err if ("rror" in l or "nvalid" in l or "arning" in l) and "x265" in l or "rror" in l][-3:]
    json.dump(res, open(f"{OUT}/{tag}.json", "w"), indent=1)
    if not a.keep and os.path.exists(out):
        os.remove(out)
    print(json.dumps({k: v for k, v in res.items() if k != "x265_info"}))


if __name__ == "__main__":
    main()
