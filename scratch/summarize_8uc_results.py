"""
Summarize 8U-C Benchmark Results.
"""
import json
import statistics
from pathlib import Path

res_path = Path("c:/_DEV/TeleM/Raporty/etap8u_c_artifacts/etap8u_c_benchmark_results.json")
with open(res_path) as f:
    data = json.load(f)

def summarize_runs(run_list, name):
    render_fps = [r["profile"]["render_fps"] for r in run_list]
    effective_fps = [r["profile"]["user_effective_fps"] for r in run_list]
    render_wall = [r["profile"]["video_render_wall_ms"] for r in run_list]
    total_wall = [r["profile"]["total_from_export_start_ms"] for r in run_list]
    
    # GPU timeline stats
    gpu_spans = []
    vp_times = []
    map_times = []
    gauge_times = []
    charts_times = []
    hud_times = []
    
    for r in run_list:
        p = r["profile"]
        if "gpu_timeline_summary" in p:
            s = p["gpu_timeline_summary"]
            gpu_spans.append(s.get("span_ms_avg", 0.0))
            vp_times.append(s.get("vp_ms_avg", 0.0))
            map_times.append(s.get("map_ms_avg", 0.0))
            gauge_times.append(s.get("gauge_ms_avg", 0.0))
            charts_times.append(s.get("charts_ms_avg", 0.0))
            hud_times.append(s.get("hud_ms_avg", 0.0))
            
    print(f"=== {name} (N={len(run_list)}) ===")
    print(f"Render FPS:    {statistics.mean(render_fps):.3f} +/- {statistics.stdev(render_fps) if len(render_fps)>1 else 0:.3f} (Runs: {[round(x, 3) for x in render_fps]})")
    print(f"Effective FPS: {statistics.mean(effective_fps):.3f} +/- {statistics.stdev(effective_fps) if len(effective_fps)>1 else 0:.3f} (Runs: {[round(x, 3) for x in effective_fps]})")
    print(f"Render Wall:   {statistics.mean(render_wall)/1000.0:.3f} s")
    print(f"Total Wall:    {statistics.mean(total_wall)/1000.0:.3f} s")
    if gpu_spans:
        print(f"GPU Span Avg:  {statistics.mean(gpu_spans):.3f} ms")
        print(f"VP Blt Avg:    {statistics.mean(vp_times):.3f} ms")
        print(f"Charts Avg:    {statistics.mean(charts_times):.3f} ms")
        print(f"Gauge Avg:     {statistics.mean(gauge_times):.3f} ms")
        print(f"Map Avg:       {statistics.mean(map_times):.3f} ms")
        print(f"Fused HUD Avg: {statistics.mean(hud_times):.3f} ms")
    print()

summarize_runs(data["direct_map_on_3x"], "3x 4K DIRECT MAP ON")
summarize_runs(data["real_map_off_3x"], "3x 4K REAL MAP OFF")
summarize_runs([data["full_5395"]], "FULL 5395-FRAME 4K RUN (DIRECT)")
