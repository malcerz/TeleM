"""
Analyze ETAP 8U-B benchmark results and GPU timeline profiles.
"""
import json
import statistics
import numpy as np
from pathlib import Path

root = Path("c:/_DEV/TeleM")
bench_file = root / "Raporty" / "etap8u_b_artifacts" / "etap8u_b_benchmark_results.json"

with open(bench_file) as f:
    data = json.load(f)

print("=== ETAP 8U-B BENCHMARK ANALYSIS ===")

def analyze_runs(run_list, label):
    render_fps = []
    effective_fps = []
    render_wall = []
    total_wall = []
    vp_gpu = []
    
    for r in run_list:
        prof = r.get("profile", {})
        wall = prof.get("etap8p_a", {})
        fps = wall.get("render_fps", 0.0)
        eff = wall.get("effective_fps", 0.0)
        r_wall = wall.get("video_render_wall_ms", 0.0) / 1000.0
        t_wall = r.get("total_wall_s", 0.0)
        
        # VP GPU completion from profile
        vp_ms = prof.get("timings", {}).get("VideoProcessor GPU completion", {}).get("median_ms", 0.0)
        
        render_fps.append(fps)
        effective_fps.append(eff)
        render_wall.append(r_wall)
        total_wall.append(t_wall)
        vp_gpu.append(vp_ms)
        
    print(f"\n--- {label} (3 Runs) ---")
    for i in range(len(run_list)):
        print(f"Run {i+1}: Render FPS={render_fps[i]:.3f}, Effective FPS={effective_fps[i]:.3f}, Render Wall={render_wall[i]:.3f}s, VP GPU={vp_gpu[i]:.3f}ms")
        
    med_fps = statistics.median(render_fps)
    med_eff = statistics.median(effective_fps)
    med_rwall = statistics.median(render_wall)
    med_twall = statistics.median(total_wall)
    med_vp = statistics.median(vp_gpu)
    print(f"-> MEDIAN: Render FPS = {med_fps:.3f}, Effective FPS = {med_eff:.3f}, Render Wall = {med_rwall:.3f}s, VP GPU = {med_vp:.3f}ms")
    return {
        "render_fps": med_fps,
        "effective_fps": med_eff,
        "render_wall": med_rwall,
        "total_wall": med_twall,
        "vp_gpu": med_vp,
    }

ref_stats = analyze_runs(data["reference_3x"], "4K REFERENCE (Two-Pass Lanczos3)")
dir_stats = analyze_runs(data["direct_3x"], "4K DIRECT (1:1 Direct GPU Blend)")

# Comparison
fps_diff = dir_stats["render_fps"] - ref_stats["render_fps"]
fps_pct = (fps_diff / ref_stats["render_fps"]) * 100.0
print(f"\n=== A/B COMPARISON (DIRECT vs REFERENCE) ===")
print(f"Render FPS Delta:    {fps_diff:+.3f} FPS ({fps_pct:+.2f}%)")
print(f"Render Wall Delta:   {dir_stats['render_wall'] - ref_stats['render_wall']:+.3f} s")
print(f"VP GPU Delta:        {dir_stats['vp_gpu'] - ref_stats['vp_gpu']:+.3f} ms")

# Map OFF
print("\n--- 4K MAP OFF CONTROL ---")
r_off = data["map_off"]
prof_off = r_off.get("profile", {})
wall_off = prof_off.get("etap8p_a", {})
print(f"Render FPS:    {wall_off.get('render_fps', 0.0):.3f} FPS")
print(f"Effective FPS: {wall_off.get('effective_fps', 0.0):.3f} FPS")

# Full 5395
print("\n--- FULL 5395-FRAME 4K RUN (DIRECT) ---")
r_5395 = data["full_5395"]
prof_5395 = r_5395.get("profile", {})
wall_5395 = prof_5395.get("etap8p_a", {})
true_e2e = prof_5395.get("true_end_to_end", {})
print(f"Encoded frames: {true_e2e.get('encoded_frames')} / 5395")
print(f"Muxed frames:   {true_e2e.get('muxed_frames')} / 5395")
print(f"Render FPS:     {wall_5395.get('render_fps', 0.0):.3f} FPS")
print(f"Effective FPS:  {wall_5395.get('effective_fps', 0.0):.3f} FPS")
print(f"Render Wall:    {wall_5395.get('video_render_wall_ms', 0.0)/1000.0:.3f} s")
print(f"Total Wall:     {r_5395.get('total_wall_s', 0.0):.3f} s")
print(f"Direct Used:    {prof_5395.get('etap5g', {}).get('map_gpu_direct_used')}")
