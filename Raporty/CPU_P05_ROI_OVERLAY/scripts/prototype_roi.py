"""CPU P0.5 stage 2 prototype: full-frame overlay (A) vs region/atlas overlay (B).

Real base video (GX010370 4K HLG, noautorotate) + real HUD frames dumped from the
export pipe.  A: current graph.  B: planned regions, atlas converted once or per
region.  Modes:
  parity : write N raw yuv420p10le frames per graph and compare bit for bit (pre-compression)
  time   : decode+overlay to -f null, N frames, CPU time per frame
Usage: prototype_roi.py parity|time <layout> <frame> <variant> [--tile T --margin M --overhead O --max N]
variant: full | roi_once | roi_each
"""
import argparse
import json
import os
import re
import subprocess
import sys
import threading
import time

import numpy as np
import psutil

sys.path.insert(0, "C:/_DEV/SportCamHUD/Raporty/CPU_P05_ROI_OVERLAY/prototype")
import cpu_hud_roi as roi  # noqa: E402

FF = r"C:\_DEV\SportCamHUD\runtime\common\ffmpeg\ffmpeg.exe"
VIDEO = r"D:\GoPro\GX010370.MP4"
ROOT = "C:/_DEV/SportCamHUD/Raporty/CPU_P05_ROI_OVERLAY"
W, H = 3840, 2160
FULL = "[0:v]null[base];[1:v]setpts=PTS-STARTPTS[ov];[base][ov]overlay=0:0:shortest=1:format=yuv420p10[v]"


def load_plan(layout, args):
    if args.manual:  # "x,y,w,h;x,y,w,h" -> fixed regions (cost-structure experiments)
        regs = [roi.Region(*map(int, r.split(","))) for r in args.manual.split(";")]
        cells, aw, ah = roi.pack_atlas(regs)
        return roi.RoiPlan(W, H, 16, tuple(cells), aw, ah)
    al = [np.fromfile(f"{ROOT}/frames/{layout}/export_hud_f{f}.rgba", dtype=np.uint8).reshape(H, W, 4)[..., 3]
          for f in (0, 80, 160, 240, 319)]
    return roi.plan_from_mask(roi.alpha_union(al), tile=args.tile, margin_px=args.margin,
                              overhead_px=args.overhead, max_regions=args.max)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("mode")
    ap.add_argument("layout")
    ap.add_argument("frame", type=int)
    ap.add_argument("variant")
    ap.add_argument("--tile", type=int, default=32)
    ap.add_argument("--margin", type=int, default=16)
    ap.add_argument("--overhead", type=int, default=60000)
    ap.add_argument("--max", type=int, default=24)
    ap.add_argument("--frames", type=int, default=300)
    ap.add_argument("--manual", default="")
    ap.add_argument("--sink", default="null", choices=["null", "ultrafast", "faster"])
    ap.add_argument("--tag", default="")
    a = ap.parse_args()
    out_dir = os.path.join(ROOT, "proto")
    os.makedirs(out_dir, exist_ok=True)
    tag = a.tag or f"{a.mode}_{a.layout}_f{a.frame}_{a.variant}"
    hud_path = f"{ROOT}/frames/{a.layout}/export_hud_f{a.frame}.rgba"
    frame = np.fromfile(hud_path, dtype=np.uint8).reshape(H, W, 4)
    cmd = [FF, "-y", "-hide_banner", "-loglevel", "info", "-nostats", "-progress", "pipe:1",
           "-noautorotate", "-ss", f"{900 * 1001 / 30000:.9f}", "-i", VIDEO]
    info = {"variant": a.variant}
    if a.variant == "full":
        cmd += ["-stream_loop", "-1", "-f", "rawvideo", "-pix_fmt", "rgba", "-s", f"{W}x{H}",
                "-framerate", "30000/1001", "-i", hud_path, "-filter_complex", FULL]
    else:
        plan = load_plan(a.layout, a)
        atlas = np.zeros((plan.atlas_h, plan.atlas_w, 4), dtype=np.uint8)
        roi.pack_into_atlas(plan, frame, atlas)
        miss = roi.uncovered_alpha_pixels(plan, frame[..., 3])
        info.update(regions=len(plan.cells), region_pct=round(100 * plan.fraction_of_canvas, 2),
                    atlas_pct=round(100 * plan.atlas_fraction, 2), uncovered_alpha_px=miss)
        apath = os.path.join(out_dir, f"atlas_{a.layout}_f{a.frame}_{a.tile}_{a.margin}.rgba")
        atlas.tofile(apath)
        g = "[0:v]null[base];" + roi.build_roi_filter(plan, convert_atlas_once=(a.variant == "roi_once"))
        cmd += ["-stream_loop", "-1", "-f", "rawvideo", "-pix_fmt", "rgba", "-s", f"{plan.atlas_w}x{plan.atlas_h}",
                "-framerate", "30000/1001", "-i", apath, "-filter_complex", g]
        info["graph"] = g
    if a.mode == "parity":
        dump = os.path.join(out_dir, tag + ".yuv")
        cmd += ["-map", "[v]" if a.variant == "full" else "[vtemp]", "-frames:v", "3", "-pix_fmt", "yuv420p10le",
                "-f", "rawvideo", dump]
    else:
        cmd += ["-map", "[v]" if a.variant == "full" else "[vtemp]", "-frames:v", str(a.frames)]
        if a.sink == "null":
            cmd += ["-pix_fmt", "yuv420p10le", "-f", "null", "-"]
        else:
            cmd += ["-c:v", "libx265", "-preset", a.sink, "-b:v", "16000k", "-profile:v", "main10",
                    "-pix_fmt", "yuv420p10le", "-an", os.path.join(out_dir, tag + ".mp4")]
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
    info.update(mode=a.mode, layout=a.layout, frame=a.frame, rc=rc, wall_s=round(wall, 3))
    if a.mode == "time":
        info["wall_fps"] = round(a.frames / wall, 2)
        if len(prog) > 2:
            n = max(f for _, f in prog)
            pts = [(t, f) for t, f in prog if n * 0.1 <= f <= n * 0.9]
            if len(pts) >= 2 and pts[-1][0] > pts[0][0]:
                info["steady_fps"] = round((pts[-1][1] - pts[0][1]) / (pts[-1][0] - pts[0][0]), 2)
        mid = [s for s in samples if s[0] > 0.8] or samples
        if mid:
            info["cores"] = round(sum(s[1] for s in mid) / len(mid), 2)
            info["core_s_per_frame"] = round(info["cores"] * wall / a.frames, 4)
    info["rss_peak_mb"] = round(rss[0] / 2**20)
    for line in err:
        m = re.search(r"encoded (\d+) frames in ([\d.]+)s \(([\d.]+) fps\), ([\d.]+) kb/s", line)
        if m:
            info["x265_fps"], info["x265_kbps"] = float(m[3]), float(m[4])
    info["errors"] = [l for l in err if "rror" in l or "Invalid" in l][-3:]
    json.dump(info, open(os.path.join(out_dir, tag + ".json"), "w"), indent=1)
    print(json.dumps({k: v for k, v in info.items() if k != "graph"}))


if __name__ == "__main__":
    main()
