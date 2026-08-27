import json
from pathlib import Path

res_path = Path("scratch/etap3a_bench/etap3a_all_results.json")
data = json.load(open(res_path))

print("=" * 110)
print("ETAP 3A COMPLETE BENCHMARK & ABLATION RESULTS")
print("=" * 110)

header = f"{'Run / Workload':<28} {'Frames':<7} {'RENDER FPS':<12} {'EFFECTIVE FPS':<14} {'above_comp (ms)':<16} {'prod_prep (ms)':<15} {'cons_nat (ms)':<14} {'pipe_tot (ms)':<14}"
print(header)
print("-" * 110)

for tag, p in data.items():
    t = p.get("timings", {})
    r_fps = p.get("etap8pa_summary", {}).get("render_fps", p.get("fps_render", 0))
    u_fps = p.get("etap8pa_summary", {}).get("user_effective_fps", p.get("fps_user_effective", 0))
    ac = t.get("above_compose", {}).get("avg_ms", 0)
    pp = t.get("producer_prepare", {}).get("avg_ms", 0)
    cn = t.get("consumer_native_call", {}).get("avg_ms", 0)
    pt = t.get("pipeline_total", {}).get("avg_ms", 0)
    cnt = p.get("frames_encoded", p.get("total_frames_encoded", p.get("frames_input", 0)))
    print(f"{tag:<28} {cnt:<7} {r_fps:<12.3f} {u_fps:<14.3f} {ac:<16.3f} {pp:<15.3f} {cn:<14.3f} {pt:<14.3f}")
