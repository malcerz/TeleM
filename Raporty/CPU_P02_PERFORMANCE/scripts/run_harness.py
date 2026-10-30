"""Run one `SportCamHUD.py --test-cpu-export` and sample CPU / RAM of the whole
process tree (main GUI process, HUD worker processes, ffmpeg) every 0.5 s.

Usage: run_harness.py --tag TAG --out-dir DIR [--frames N] [--start-frame S]
                      [--env KEY=VAL ...]
Writes DIR/TAG.mp4, TAG.result.json (harness), TAG.stdout.log, TAG.resources.json.
"""
import argparse
import json
import os
import re
import subprocess
import threading
import time

import psutil

REPO = r"C:\_DEV\SportCamHUD"
VIDEO = r"D:\GoPro\GX010370.MP4"
FIT = r"D:\GoPro\2026-10-13_15-02-49.fit"
LAYOUT = r"C:\_DEV\SportCamHUD\def_layout.json"


def role(proc, root_pid):
    try:
        name = (proc.name() or "").lower()
        if proc.pid == root_pid:
            return "main"
        if "ffmpeg" in name:
            return "ffmpeg"
        if "python" in name:
            return "worker"
        return "other"
    except psutil.Error:
        return "other"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", required=True)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--frames", type=int, default=150)
    ap.add_argument("--start-frame", type=int, default=900)
    ap.add_argument("--env", action="append", default=[])
    ap.add_argument("--extra", default="", help="extra harness CLI args, e.g. '--bitrate 16M --profile fast'")
    a = ap.parse_args()
    a.out_dir = os.path.abspath(a.out_dir)
    os.makedirs(a.out_dir, exist_ok=True)
    base = os.path.join(a.out_dir, a.tag)
    env = dict(os.environ)
    env["QT_QPA_PLATFORM"] = "offscreen"
    env["TELEM_CPU_HARNESS_TRACE"] = "1"
    for kv in a.env:
        k, v = kv.split("=", 1)
        env[k] = v
    cmd = ["python", "SportCamHUD.py", "--test-cpu-export", "--mode", "direct", "--video", VIDEO,
           "--fit", FIT, "--layout", LAYOUT, "--start-frame", str(a.start_frame),
           "--frames", str(a.frames), "--wait-prepared", "--output", base + ".mp4",
           "--result-json", base + ".result.json"] + a.extra.split()
    log = open(base + ".stdout.log", "wb")
    mem0 = psutil.virtual_memory()
    t0 = time.perf_counter()
    p = subprocess.Popen(cmd, cwd=REPO, env=env, stdout=log, stderr=subprocess.STDOUT)
    root = psutil.Process(p.pid)
    cpu_last = {}
    series = []
    stop = threading.Event()
    cores = psutil.cpu_count()

    def sampler():
        psutil.cpu_percent(None)
        last_t = time.perf_counter()
        while not stop.is_set():
            time.sleep(0.5)
            now = time.perf_counter()
            dt = now - last_t
            last_t = now
            agg = {}
            try:
                procs = [root] + root.children(recursive=True)
            except psutil.Error:
                continue
            for pr in procs:
                try:
                    r = role(pr, p.pid)
                    ct = pr.cpu_times()
                    c = ct.user + ct.system
                    d = (c - cpu_last.get(pr.pid, 0.0)) / dt
                    cpu_last[pr.pid] = c
                    rss = pr.memory_info().rss
                    a_ = agg.setdefault(r, {"cores": 0.0, "rss": 0, "n": 0})
                    a_["cores"] += d
                    a_["rss"] += rss
                    a_["n"] += 1
                except psutil.Error:
                    pass
            vm = psutil.virtual_memory()
            series.append({"t": round(now - t0, 2), "sys_cpu": psutil.cpu_percent(None),
                           "sys_used_gb": round((vm.total - vm.available) / 2**30, 2),
                           "roles": {k: {"cores": round(v["cores"], 2),
                                         "rss_mb": round(v["rss"] / 2**20, 1), "n": v["n"]}
                                     for k, v in agg.items()}})

    th = threading.Thread(target=sampler, daemon=True)
    th.start()
    rc = p.wait()
    wall = time.perf_counter() - t0
    stop.set()
    th.join(2)
    log.close()

    summary = {"tag": a.tag, "env": a.env, "extra": a.extra, "frames": a.frames, "start_frame": a.start_frame,
               "returncode": rc, "process_wall_s": round(wall, 2),
               "sys_used_gb_before": round((mem0.total - mem0.available) / 2**30, 2)}
    if series:
        summary["sys_used_gb_peak"] = max(s["sys_used_gb"] for s in series)
        # window = samples between 25% and 90% of the run (steady-state-ish)
        n = len(series)
        win = series[int(n * .25):int(n * .9)] or series
        summary["window_s"] = [win[0]["t"], win[-1]["t"]]
        summary["sys_cpu_pct_window"] = round(sum(s["sys_cpu"] for s in win) / len(win), 1)
        roles = {r for s in series for r in s["roles"]}
        summary["cores_window"] = {
            r: round(sum(s["roles"].get(r, {}).get("cores", 0) for s in win) / len(win), 2) for r in roles}
        summary["rss_peak_mb"] = {
            r: max(s["roles"].get(r, {}).get("rss_mb", 0) for s in series) for r in roles}
        summary["n_procs_peak"] = {
            r: max(s["roles"].get(r, {}).get("n", 0) for s in series) for r in roles}
    try:
        txt = open(base + ".stdout.log", "r", errors="replace").read()
        m = re.search(r"\[STREAM\] SHM pool: (\d+) slots .*= (\d+) MB total \| workers=(\d+)", txt)
        if m:
            summary["shm_slots"], summary["shm_mb"], summary["workers"] = int(m[1]), int(m[2]), int(m[3])
        m = re.search(r"\[BENCH RESULT\][^\n]*", txt)
        if m:
            summary["bench_line"] = m[0]
    except OSError:
        pass
    try:
        rj = json.load(open(base + ".result.json"))
        m = rj.get("cpu_stream_metrics", {})
        summary["harness"] = {k: rj.get(k) for k in ("success", "error", "elapsed_s", "total_frames", "effective_fps",
                                                      "project_load_until_click_s")}
        summary["stream"] = {k: m.get(k) for k in (
            "stream_wall_s", "first_piped_frame_s", "pipe_first_to_last_s", "pipe_steady_fps",
            "pipe_steady_window_frames", "ffmpeg_drain_and_finalize_s", "frames_written", "workers",
            "shm_slots")}
        tr = m.get("ffmpeg_trace", [])
        for line in tr:
            mm = re.search(r"encoded (\d+) frames in ([\d.]+)s \(([\d.]+) fps\), ([\d.]+) kb/s", line)
            if mm:
                summary["x265"] = {"frames": int(mm[1]), "s": float(mm[2]), "fps": float(mm[3]), "kbps": float(mm[4])}
            if "Rate Control" in line:
                summary["x265_rc"] = line.split("]:", 1)[-1].strip()
        v = rj.get("validation", {})
        cv = rj.get("cpu_validation", {})
        summary["validation"] = {"valid": v.get("valid"), "actual_video_frames": v.get("actual_video_frames"),
                                 "av": cv.get("av"), "color_valid": (cv.get("output_color") or {}).get("color_valid", cv.get("color_valid"))}
        summary["output_bytes"] = rj.get("output_size_bytes")
    except Exception as e:  # noqa: BLE001
        summary["result_parse_error"] = repr(e)
    json.dump({"summary": summary, "series": series}, open(base + ".resources.json", "w"), indent=1)
    print(json.dumps(summary, indent=1))


if __name__ == "__main__":
    main()
