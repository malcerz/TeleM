from __future__ import annotations

import json
import re
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VIDEO = ROOT / "Video" / "GX030120.MP4"
GEOM = ROOT / "scratch" / "etap5b3_geometry" / "geometry_audit.json"
RUNS = 3
FRAMES = 5400


def sample_gpu():
    proc = subprocess.Popen(["nvidia-smi", "dmon", "-s", "pucvmet", "-d", "1"], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    return proc


def parse_dmon(text):
    vals = {"sm": [], "enc": [], "dec": []}
    for line in text.splitlines():
        if not re.match(r"^\s*0\s+", line):
            continue
        cols = line.split()
        if len(cols) >= 9:
            for key, idx in (("sm", 4), ("enc", 6), ("dec", 7)):
                try: vals[key].append(float(cols[idx]))
                except ValueError: pass
    return {k: (sum(v) / len(v) if v else None, max(v) if v else None, len(v)) for k, v in vals.items()}


def run_case(name, geom):
    regions = geom["regions"]
    atlas_w, atlas_h = geom["atlas_w"], geom["atlas_h"]
    chains = []
    overlays = []
    labels = "".join(f"[ov_raw_{i}]" for i in range(len(regions)))
    prev = "[base]"
    for i, r in enumerate(regions):
        dx, dy, ax, ay, rw, rh = r["dest"][0], r["dest"][1], r["atlas"][0], r["atlas"][1], r["dest"][2], r["dest"][3]
        chains.append(f"[ov_raw_{i}]crop={rw}:{rh}:{ax}:{ay},scale={rw*2}:{rh*2}:flags=bilinear,format=yuva420p,hwupload_cuda[ov_{i}]")
        nxt = f"[step_{i}]" if i < len(regions) - 1 else "[vout]"
        overlays.append(f"{prev}[ov_{i}]overlay_cuda=x={dx*2}:y={dy*2}{nxt}")
        prev = nxt
    fc = "[0:v]scale_cuda=format=yuv420p[base];" + f"[1:v]setpts=PTS-STARTPTS,format=rgba,split={len(regions)}{labels};" + ";".join(chains) + ";" + ";".join(overlays)
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-hwaccel", "cuda", "-hwaccel_output_format", "cuda", "-i", str(VIDEO),
           "-f", "lavfi", "-i", f"color=c=black@0.0:s={atlas_w}x{atlas_h}:r=30000/1001", "-filter_complex", fc,
           "-map", "[vout]", "-frames:v", str(FRAMES), "-c:v", "hevc_nvenc", "-preset", "p1", "-tune", "hq", "-rc", "vbr", "-cq", "24", "-pix_fmt", "cuda", "-gpu", "0", "-f", "null", "-"]
    results = []
    for rep in range(1, RUNS + 1):
        mon = sample_gpu()
        t0 = time.perf_counter()
        p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        elapsed = time.perf_counter() - t0
        try: mon.terminate()
        except Exception: pass
        try: out, _ = mon.communicate(timeout=3)
        except subprocess.TimeoutExpired:
            mon.kill(); out, _ = mon.communicate()
        if p.returncode:
            raise RuntimeError(f"{name} run {rep} failed: {p.stderr[-1000:]}")
        results.append({"run": rep, "elapsed_s": elapsed, "fps": FRAMES / elapsed, "gpu": parse_dmon(out)})
        print(f"{name} run {rep}: {FRAMES / elapsed:.2f} FPS, {elapsed:.2f}s, gpu={results[-1]['gpu']}", flush=True)
    fps = sorted(x["fps"] for x in results)
    return {"name": name, "regions": len(regions), "atlas_w": atlas_w, "atlas_h": atlas_h, "runs": results,
            "median_fps": fps[len(fps)//2], "median_elapsed_s": sorted(x["elapsed_s"] for x in results)[len(results)//2]}


def main():
    data = json.loads(GEOM.read_text(encoding="utf-8"))
    cases = {}
    for maximum in (3, 4, 5):
        item = data["by_max_regions"][str(maximum)]
        regions = [{"dest": list(x["dest"]), "atlas": list(x["atlas"])} for x in item["packed"]]
        cases[str(maximum)] = {"regions": regions, "atlas_w": item["atlas_w"], "atlas_h": item["atlas_h"]}
    results = [run_case(f"{n}-regions", cases[n]) for n in ("3", "4", "5")]
    (ROOT / "scratch" / "etap5b3_geometry" / "cuda_benchmark.json").write_text(json.dumps(results, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
