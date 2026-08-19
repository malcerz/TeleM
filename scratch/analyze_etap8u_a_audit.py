"""
Analyze ETAP 8U-A audit results and extract GPU timestamps, filter comparisons, and quality metrics.
"""
import json
import statistics
import numpy as np
from pathlib import Path

root = Path("c:/_DEV/TeleM")
summary_file = root / "Raporty" / "etap8u_a_artifacts" / "etap8u_a_audit_results.json"

with open(summary_file) as f:
    data = json.load(f)

print("=== ETAP 8U-A AUDIT ANALYSIS ===")

import csv

def parse_gpu_csv(csv_path: Path):
    if not csv_path.exists():
        return {}
    
    rows = []
    with open(csv_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for r in reader:
            try:
                rows.append({
                    "span_ms": float(r.get("gpu_span_ms") or r.get("span_ms", 0.0)),
                    "vp_ms": float(r.get("vp_blt_ms") or r.get("vp_ms", 0.0)),
                    "charts_ms": float(r.get("charts_ms", 0.0)),
                    "gauge_ms": float(r.get("gauge_ms", 0.0)),
                    "map_ms": float(r.get("map_ms", 0.0)),
                    "hud_ms": float(r.get("hud_nv12_ms") or r.get("hud_ms", 0.0)),
                })
            except (ValueError, KeyError):
                continue
                
    if not rows:
        return {}
        
    spans = [r["span_ms"] for r in rows if r["span_ms"] > 0]
    vps = [r["vp_ms"] for r in rows if r["vp_ms"] >= 0]
    charts = [r["charts_ms"] for r in rows if r["charts_ms"] >= 0]
    gauges = [r["gauge_ms"] for r in rows if r["gauge_ms"] >= 0]
    maps = [r["map_ms"] for r in rows if r["map_ms"] >= 0]
    huds = [r["hud_ms"] for r in rows if r["hud_ms"] >= 0]
    
    def q(lst):
        if not lst: return 0.0, 0.0
        s = sorted(lst)
        med = statistics.median(s)
        p95 = s[int(len(s) * 0.95)]
        return med, p95

    return {
        "count": len(rows),
        "span": q(spans),
        "vp": q(vps),
        "charts": q(charts),
        "gauge": q(gauges),
        "map": q(maps),
        "hud": q(huds),
    }

def print_run_stats(label, r_obj):
    run_name = r_obj.get("run_name")
    prof = r_obj.get("profile", {})
    wall = prof.get("etap8p_a", {})
    csv_p = root / "Raporty" / "etap8u_a_artifacts" / f"{run_name}.mp4.gpu_timeline.csv"
    gpu = parse_gpu_csv(csv_p)
    
    print(f"\n--- {label} ---")
    print(f"Render FPS:    {wall.get('render_fps', 0.0):.3f} FPS")
    print(f"Effective FPS: {wall.get('effective_fps', 0.0):.3f} FPS")
    print(f"Render Wall:   {wall.get('video_render_wall_ms', 0.0)/1000.0:.3f} s")
    print(f"GPU Span:      {gpu.get('span', (0,0))[0]:.3f} ms (p95={gpu.get('span', (0,0))[1]:.3f} ms)")
    print(f"GPU Map:       {gpu.get('map', (0,0))[0]:.3f} ms (p95={gpu.get('map', (0,0))[1]:.3f} ms)")
    print(f"GPU VP Blt:    {gpu.get('vp', (0,0))[0]:.3f} ms")
    print(f"GPU HUD/NV12:  {gpu.get('hud', (0,0))[0]:.3f} ms")
    print(f"GPU Charts:    {gpu.get('charts', (0,0))[0]:.3f} ms | Gauge: {gpu.get('gauge', (0,0))[0]:.3f} ms")

# Baseline 3x Lanczos
print("\n=== 1. 4K BASELINE 3x LANCZOS ===")
fps_list = []
gpu_map_list = []
gpu_span_list = []
for i, r in enumerate(data["baseline_lanczos_4k"]):
    run_name = r.get("run_name")
    prof = r.get("profile", {})
    wall = prof.get("etap8p_a", {})
    csv_p = root / "Raporty" / "etap8u_a_artifacts" / f"{run_name}.mp4.gpu_timeline.csv"
    gpu = parse_gpu_csv(csv_p)
    fps_list.append(wall.get("render_fps", 0.0))
    gpu_map_list.append(gpu.get("map", (0,0))[0])
    gpu_span_list.append(gpu.get("span", (0,0))[0])
    print(f"Run {i+1}: Render FPS={wall.get('render_fps', 0.0):.3f}, GPU Map={gpu.get('map', (0,0))[0]:.3f} ms, GPU Span={gpu.get('span', (0,0))[0]:.3f} ms")

print(f"-> Median 4K Lanczos: Render FPS = {statistics.median(fps_list):.3f}, GPU Map = {statistics.median(gpu_map_list):.3f} ms, GPU Span = {statistics.median(gpu_span_list):.3f} ms")

# Filter variants
print_run_stats("4K BILINEAR FILTER", data["bilinear_4k"])
print_run_stats("4K BICUBIC FILTER", data["bicubic_4k"])
print_run_stats("4K MAP OFF CONTROL", data["map_off_4k"])
print_run_stats("1080p LANCZOS BASELINE", data["1080p"])

# Geometry summary
geo = data.get("geometry", {})
print("\n=== 2. GEOMETRY SUMMARY ===")
print(f"4K Source Dimensions:      {geo.get('4k_src')}")
print(f"4K Destination Dimensions: {geo.get('4k_dst')}")
print(f"1080p Source Dimensions:   {geo.get('1080p_src')}")
print(f"1080p Destination:         {geo.get('1080p_dst')}")
print(f"Consecutive Frame Pixel Change: Mean={geo.get('change_ratio_mean', 0)*100:.2f}%, Median={geo.get('change_ratio_median', 0)*100:.2f}%")
