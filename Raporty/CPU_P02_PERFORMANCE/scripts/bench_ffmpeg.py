"""CPU P0.2 standalone FFmpeg ablations (variants A, B).

Sequential, one ffmpeg per invocation.  Samples process CPU time / RSS of the
ffmpeg process every 0.25 s and parses -progress output for first-frame and
steady-state (10%..90% of frames) FPS.

Usage: bench_ffmpeg.py <variant> [--preset P] [--frames N] [--start-frame S]
                       [--rc prod|crf24|abr16384|abr40m] [--tag TAG] --out-dir DIR
Variants: decode (A0), x265 (A), overlay_png (B1), overlay_pipe (B2)
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
FPS_NUM, FPS_DEN = 30000, 1001
W, H = 3840, 2160
HUD_PNG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static_hud_rgba.png")
COLOR = ["-color_primaries", "bt2020", "-color_trc", "arib-std-b67",
         "-colorspace", "bt2020nc", "-color_range", "pc"]
OVERLAY_FC = ("[0:v]null[base];[1:v]setpts=PTS-STARTPTS[ov];"
              "[base][ov]overlay=0:0:shortest=1:format=yuv420p10[v]")


def make_static_hud():
    if os.path.exists(HUD_PNG):
        return
    from PIL import Image, ImageDraw
    im = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle((60, 60, 1260, 520), 30, fill=(0, 0, 0, 140), outline=(255, 255, 255, 230), width=6)
    d.rounded_rectangle((60, 1500, 1500, 2100), 30, fill=(10, 10, 10, 150))
    d.ellipse((2900, 1400, 3700, 2100), fill=(20, 30, 20, 170), outline=(255, 255, 255, 255), width=8)
    for i in range(40):
        d.rectangle((100 + i * 30, 1900 - (i * 37) % 300, 118 + i * 30, 2060), fill=(255, 80, 60, 220))
    d.text((120, 120), "SportCamHUD static overlay 123.4 km/h", fill=(255, 255, 255, 255))
    im.save(HUD_PNG)


def build_cmd(variant, preset, rc, frames, start_frame, out):
    ss = ["-ss", f"{start_frame * FPS_DEN / FPS_NUM:.9f}"] if start_frame else []
    vin = ["-noautorotate", *ss, "-i", VIDEO]
    enc = ["-c:v", "libx265", "-preset", preset]
    if rc == "crf24":
        enc += ["-crf", "24"]
    elif rc == "prod":  # exactly the production arguments: crf + -b:v 40M
        enc += ["-crf", "24", "-b:v", "40M"]
    elif rc.startswith("abr"):
        enc += ["-b:v", {"abr16384": "16384k", "abr40m": "40000k"}[rc]]
    enc += ["-profile:v", "main10", "-pix_fmt", "yuv420p10le", *COLOR]
    base = [FF, "-y", "-hide_banner", "-loglevel", "info", "-nostats", "-progress", "pipe:1"]
    tail = ["-frames:v", str(frames), "-an", "-map_metadata", "-1", out]
    if variant == "decode":
        return base + vin + ["-map", "0:v:0", "-frames:v", str(frames), "-f", "null", "-"]
    if variant == "x265":
        return base + vin + ["-map", "0:v:0"] + enc + tail
    if variant == "overlay_png":
        return (base + vin + ["-loop", "1", "-framerate", f"{FPS_NUM}/{FPS_DEN}", "-i", HUD_PNG,
                              "-filter_complex", OVERLAY_FC, "-map", "[v]"] + enc + tail)
    if variant == "overlay_pipe":
        return (base + vin + ["-f", "rawvideo", "-pix_fmt", "rgba", "-s", f"{W}x{H}",
                              "-r", f"{FPS_NUM}/{FPS_DEN}", "-i", "pipe:0",
                              "-filter_complex", OVERLAY_FC, "-map", "[v]"] + enc + tail)
    raise SystemExit("unknown variant " + variant)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("variant")
    ap.add_argument("--preset", default="medium")
    ap.add_argument("--rc", default="prod")
    ap.add_argument("--frames", type=int, default=150)
    ap.add_argument("--start-frame", type=int, default=900)
    ap.add_argument("--tag", default="")
    ap.add_argument("--out-dir", required=True)
    a = ap.parse_args()
    os.makedirs(a.out_dir, exist_ok=True)
    make_static_hud()
    tag = a.tag or f"{a.variant}_{a.preset}_{a.rc}_{a.frames}f"
    out = os.path.join(a.out_dir, tag + ".mp4")
    cmd = build_cmd(a.variant, a.preset, a.rc, a.frames, a.start_frame, out)
    t0 = time.perf_counter()
    p = subprocess.Popen(cmd, stdin=subprocess.PIPE if a.variant == "overlay_pipe" else None,
                         stdout=subprocess.PIPE, stderr=subprocess.PIPE, bufsize=0)
    ps = psutil.Process(p.pid)
    samples, stop = [], threading.Event()

    def sampler():
        last_cpu, last_t = None, None
        psutil.cpu_percent(None)
        while not stop.is_set():
            try:
                ct = ps.cpu_times()
                cpu = ct.user + ct.system
                now = time.perf_counter()
                rss = ps.memory_info().rss
                sysp = psutil.cpu_percent(None)
                if last_cpu is not None:
                    samples.append((now - t0, (cpu - last_cpu) / (now - last_t), rss, sysp))
                last_cpu, last_t = cpu, now
            except psutil.Error:
                break
            time.sleep(0.25)

    threading.Thread(target=sampler, daemon=True).start()

    prog = []  # (t, frame)

    def read_stdout():
        buf = b""
        while True:
            chunk = p.stdout.read(4096)
            if not chunk:
                break
            buf += chunk
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                m = re.match(rb"frame=(\d+)", line.strip())
                if m:
                    prog.append((time.perf_counter() - t0, int(m.group(1))))

    err_lines = []

    def read_stderr():
        for raw in iter(p.stderr.readline, b""):
            err_lines.append(raw.decode("utf-8", "replace").rstrip())

    ts = threading.Thread(target=read_stdout, daemon=True)
    te = threading.Thread(target=read_stderr, daemon=True)
    ts.start()
    te.start()

    if a.variant == "overlay_pipe":
        import numpy as np
        from PIL import Image
        buf = np.asarray(Image.open(HUD_PNG).convert("RGBA")).copy()
        mv = memoryview(buf).cast("B")
        try:
            for _ in range(a.frames + 4):
                p.stdin.write(mv)
        except (BrokenPipeError, OSError):
            pass
        try:
            p.stdin.close()
        except OSError:
            pass
    rc = p.wait()
    wall = time.perf_counter() - t0
    stop.set()
    ts.join(2)
    te.join(2)

    res = {"variant": a.variant, "preset": a.preset, "rc": a.rc, "frames": a.frames,
           "start_frame": a.start_frame, "returncode": rc, "wall_s": round(wall, 3),
           "wall_fps": round(a.frames / wall, 3), "cmd": " ".join(cmd)}
    if prog:
        res["first_frame_s"] = round(next((t for t, f in prog if f >= 1), prog[0][0]), 3)
        n = max(f for _, f in prog)
        pts = [(t, f) for t, f in prog if n * 0.1 <= f <= n * 0.9]
        if len(pts) >= 2 and pts[-1][0] > pts[0][0]:
            res["steady_fps_10_90"] = round((pts[-1][1] - pts[0][1]) / (pts[-1][0] - pts[0][0]), 3)
        res["last_progress_frame"] = n
    for line in err_lines:
        m = re.search(r"encoded (\d+) frames in ([\d.]+)s \(([\d.]+) fps\), ([\d.]+) kb/s", line)
        if m:
            res["x265_frames"], res["x265_s"], res["x265_fps"], res["x265_kbps"] = (
                int(m[1]), float(m[2]), float(m[3]), float(m[4]))
        if "Rate Control" in line:
            res["x265_rc"] = line.split("]:", 1)[-1].strip()
        if "frame threads" in line:
            res["x265_frame_threads"] = line.split(":", 1)[-1].strip()
    if samples:
        mid = [s for s in samples if s[0] > 1.0] or samples
        res["ffmpeg_cpu_cores_avg"] = round(sum(s[1] for s in mid) / len(mid), 2)
        res["ffmpeg_cpu_pct_of_16"] = round(100 * res["ffmpeg_cpu_cores_avg"] / (os.cpu_count() or 16), 1)
        res["system_cpu_pct_avg"] = round(sum(s[3] for s in mid) / len(mid), 1)
        res["ffmpeg_rss_peak_mb"] = round(max(s[2] for s in samples) / 2**20, 1)
    if os.path.exists(out):
        res["output_bytes"] = os.path.getsize(out)
    res["stderr_errors"] = [x for x in err_lines if "error" in x.lower()][-5:]
    with open(os.path.join(a.out_dir, tag + ".json"), "w") as f:
        json.dump(res, f, indent=1)
    print(json.dumps({k: v for k, v in res.items() if k != "cmd"}))


if __name__ == "__main__":
    main()
