"""
Generate comprehensive comparative metrics for ETAP 8U-C Report.
"""
import json
import statistics
from pathlib import Path

res_path = Path("c:/_DEV/TeleM/Raporty/etap8u_c_artifacts/etap8u_c_benchmark_results.json")
with open(res_path) as f:
    data = json.load(f)

def extract_summary(runs):
    render_fps = [r["profile"]["etap8p_a"]["render_fps"] for r in runs]
    eff_fps = [r["profile"]["etap8p_a"]["effective_fps"] for r in runs]
    render_wall = [r["profile"]["etap8p_a"]["video_render_wall_ms"] / 1000.0 for r in runs]
    total_wall = [r["profile"]["etap8p_a"]["total_from_export_start_ms"] / 1000.0 for r in runs]
    
    timings = {}
    for sname in runs[0]["profile"]["timings"].keys():
        timings[sname] = {
            "avg": statistics.mean([r["profile"]["timings"][sname]["avg_ms"] for r in runs]),
            "median": statistics.mean([r["profile"]["timings"][sname]["median_ms"] for r in runs]),
            "p95": statistics.mean([r["profile"]["timings"][sname]["p95_ms"] for r in runs]),
        }
        
    return {
        "render_fps_mean": statistics.mean(render_fps),
        "render_fps_stdev": statistics.stdev(render_fps) if len(render_fps) > 1 else 0.0,
        "render_fps_runs": render_fps,
        "eff_fps_mean": statistics.mean(eff_fps),
        "eff_fps_stdev": statistics.stdev(eff_fps) if len(eff_fps) > 1 else 0.0,
        "eff_fps_runs": eff_fps,
        "render_wall_mean": statistics.mean(render_wall),
        "total_wall_mean": statistics.mean(total_wall),
        "timings": timings,
    }

s_direct = extract_summary(data["direct_map_on_3x"])
s_map_off = extract_summary(data["real_map_off_3x"])
s_5395 = extract_summary([data["full_5395"]])

print("================================================================================")
print("=== ETAP 8U-C BENCHMARK RESULTS COMPARISON ===")
print("================================================================================")
print(f"Metric                       | 3x DIRECT MAP ON         | 3x REAL MAP OFF          | Delta (MAP OFF vs DIRECT)")
print("-----------------------------+--------------------------+--------------------------+--------------------------")
print(f"Render FPS (mean +/- sd)     | {s_direct['render_fps_mean']:.3f} +/- {s_direct['render_fps_stdev']:.3f} fps  | {s_map_off['render_fps_mean']:.3f} +/- {s_map_off['render_fps_stdev']:.3f} fps  | +{s_map_off['render_fps_mean'] - s_direct['render_fps_mean']:.3f} fps (+{(s_map_off['render_fps_mean']/s_direct['render_fps_mean']-1)*100:.2f}%)")
print(f"Effective FPS (mean +/- sd)  | {s_direct['eff_fps_mean']:.3f} +/- {s_direct['eff_fps_stdev']:.3f} fps  | {s_map_off['eff_fps_mean']:.3f} +/- {s_map_off['eff_fps_stdev']:.3f} fps  | +{s_map_off['eff_fps_mean'] - s_direct['eff_fps_mean']:.3f} fps (+{(s_map_off['eff_fps_mean']/s_direct['eff_fps_mean']-1)*100:.2f}%)")
print(f"Render Wall Time (mean)      | {s_direct['render_wall_mean']:.3f} s                 | {s_map_off['render_wall_mean']:.3f} s                 | -{s_direct['render_wall_mean'] - s_map_off['render_wall_mean']:.3f} s")
print(f"Total Wall Time (mean)       | {s_direct['total_wall_mean']:.3f} s                 | {s_map_off['total_wall_mean']:.3f} s                 | -{s_direct['total_wall_mean'] - s_map_off['total_wall_mean']:.3f} s")
print("-----------------------------+--------------------------+--------------------------+--------------------------")
print(f"Individual Direct Runs:      | {[round(x, 3) for x in s_direct['render_fps_runs']]}")
print(f"Individual Map Off Runs:     | {[round(x, 3) for x in s_map_off['render_fps_runs']]}")
print("================================================================================")
print(f"Full 5395 Run: Render FPS = {s_5395['render_fps_mean']:.3f}, Effective FPS = {s_5395['eff_fps_mean']:.3f}, Total Wall = {s_5395['total_wall_mean']:.3f} s (Frames: 5395/5395)")
print("================================================================================")

key_stages = [
    "MF ReadSample/decode availability",
    "compose_overlay",
    "map_cpu_upload",
    "gauge_tobytes",
    "gauge_upload",
    "HUD dirty extract",
    "PIL/buffer preparation",
    "update_hud",
    "HUD texture upload",
    "VideoProcessor CPU submit",
    "VideoProcessor GPU completion",
    "GPU wait/synchronization",
    "AMF submit/backpressure",
    "AMF QueryOutput",
    "producer_prepare",
    "consumer_upload",
    "consumer_native_call",
    "pipeline_total",
]

print("\n=== DETAILED STAGE TIMINGS (AVG ms) ===")
print(f"{'Stage Name':<36} | {'DIRECT MAP ON':<14} | {'REAL MAP OFF':<14} | {'Full 5395 DIRECT':<16}")
print("-" * 88)
for k in key_stages:
    d_val = s_direct["timings"].get(k, {}).get("avg", 0.0)
    m_val = s_map_off["timings"].get(k, {}).get("avg", 0.0)
    f_val = s_5395["timings"].get(k, {}).get("avg", 0.0)
    print(f"{k:<36} | {d_val:>10.3f} ms | {m_val:>10.3f} ms | {f_val:>12.3f} ms")
