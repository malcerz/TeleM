from __future__ import annotations

import json
import re
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VIDEO = ROOT / "Video" / "GX030120.MP4"
FRAMES = 5400
RUNS = 3


def sample_gpu():
    return subprocess.Popen(["nvidia-smi", "dmon", "-s", "pucvmet", "-d", "1"], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)


def parse_dmon(text):
    vals = {"sm": [], "enc": [], "dec": []}
    for line in text.splitlines():
        if not re.match(r"^\s*0\s+", line): continue
        cols = line.split()
        if len(cols) < 9: continue
        for key, idx in (("sm", 4), ("enc", 6), ("dec", 7)):
            try: vals[key].append(float(cols[idx]))
            except ValueError: pass
    return {k: (sum(v)/len(v) if v else None, max(v) if v else None, len(v)) for k, v in vals.items()}


def run_case(name, atlas, rects):
    chains, overlays = [], []
    labels = "".join(f"[ov_raw_{i}]" for i in range(len(rects)))
    prev = "[base]"
    for i, r in enumerate(rects):
        dx, dy, ax, ay, rw, rh = r
        chains.append(f"[ov_raw_{i}]crop={rw}:{rh}:{ax}:{ay},scale={rw*2}:{rh*2}:flags=bilinear,format=yuva420p,hwupload_cuda[ov_{i}]")
        nxt = f"[step_{i}]" if i < len(rects)-1 else "[vout]"
        overlays.append(f"{prev}[ov_{i}]overlay_cuda=x={dx*2}:y={dy*2}{nxt}")
        prev = nxt
    fc = "[0:v]scale_cuda=format=yuv420p[base];" + f"[1:v]setpts=PTS-STARTPTS,format=rgba,split={len(rects)}{labels};" + ";".join(chains) + ";" + ";".join(overlays)
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-hwaccel", "cuda", "-hwaccel_output_format", "cuda", "-i", str(VIDEO), "-f", "lavfi", "-i", f"color=c=black@0.0:s={atlas[0]}x{atlas[1]}:r=30000/1001", "-filter_complex", fc, "-map", "[vout]", "-frames:v", str(FRAMES), "-c:v", "hevc_nvenc", "-preset", "p1", "-tune", "hq", "-rc", "vbr", "-cq", "24", "-pix_fmt", "cuda", "-gpu", "0", "-f", "null", "-"]
    runs = []
    for rep in range(1, RUNS+1):
        mon = sample_gpu(); t0 = time.perf_counter()
        p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        elapsed = time.perf_counter()-t0
        mon.terminate()
        try: out, _ = mon.communicate(timeout=3)
        except subprocess.TimeoutExpired:
            mon.kill(); out, _ = mon.communicate()
        if p.returncode: raise RuntimeError(f"{name} run {rep}: {p.stderr[-1000:]}")
        item = {"run": rep, "elapsed_s": elapsed, "fps": FRAMES/elapsed, "gpu": parse_dmon(out)}
        runs.append(item); print(f"{name} run {rep}: {item['fps']:.2f} FPS, {elapsed:.2f}s, gpu={item['gpu']}", flush=True)
    ordered = sorted(r["fps"] for r in runs)
    return {"name": name, "atlas": list(atlas), "rects": rects, "runs": runs, "median_fps": ordered[1], "median_elapsed_s": sorted(r["elapsed_s"] for r in runs)[1]}


def main():
    audit = json.loads((ROOT/"scratch/etap5b5_geometry_audit.json").read_text(encoding="utf-8"))
    validation = json.loads((ROOT/"scratch/etap5b5_candidate_validation.json").read_text(encoding="utf-8"))
    cases = {
        "MAX3_GRID_OFF": audit["off"]["max"]["3"],
        "MAX4_GRID_OFF": audit["off"]["max"]["4"],
        "MAX4_GRID16": {"atlas": validation["atlas"], "rects": validation["regions"]},
    }
    results = []
    for name, data in cases.items(): results.append(run_case(name, data["atlas"], data.get("rects", [])))
    (ROOT/"scratch/etap5b5_cuda_benchmark.json").write_text(json.dumps(results, indent=2), encoding="utf-8")


if __name__ == "__main__": main()
