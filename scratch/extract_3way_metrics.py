import json
from pathlib import Path

prof_a_path = Path("scratch/map_rotate_test/benchmark_4k_GPU_MAP_ROTATE_OFF_BASELINE_1131f.mp4.amd_profile.json")
prof_b_path = Path("scratch/map_rotate_test/benchmark_4k_GPU_MAP_ROTATE_ON_1131f.mp4.amd_profile.json")
prof_c_path = Path("scratch/etap1c_test/full1131_mode_c_combined.mp4.amd_profile.json")

def load_profile(p):
    with open(p, "r", encoding="utf-8") as f:
        return json.load(f)

pa = load_profile(prof_a_path)
pb = load_profile(prof_b_path)
pc = load_profile(prof_c_path)

stages = [
    "map_cpu_upload",
    "compose_overlay",
    "above_compose",
    "above_exact_crop",
    "above_region_to_bytes",
    "above_region_upload",
    "above_tight_bbox_collect",
    "above_total",
    "PIL/buffer preparation",
    "update_hud",
    "producer_prepare",
    "consumer_upload",
    "consumer_native_call",
    "pipeline_total",
]

print(f"{'Metric':<26} | {'MAP1 CPU (A)':>14} | {'GPU MAP (B)':>14} | {'COMBINED (C)':>14} | {'Zysk C vs A':>14}")
print("-" * 93)

for st in stages:
    va = pa["timings"].get(st, {}).get("avg_ms", 0.0)
    vb = pb["timings"].get(st, {}).get("avg_ms", 0.0)
    vc = pc["timings"].get(st, {}).get("avg_ms", 0.0)
    gain = va - vc
    pct = ((va - vc) / va * 100.0) if va > 0 else 0.0
    print(f"{st:<26} | {va:11.3f} ms | {vb:11.3f} ms | {vc:11.3f} ms | -{gain:6.3f} ms ({pct:4.1f}%)")

print("-" * 93)
# FPS and Wall clock
wa = pa.get("etap8p_a_wall_summary", {})
wb = pb.get("etap8p_a_wall_summary", {})
wc = pc.get("etap8p_a_wall_summary", {})

fps_render_a = wa.get("RENDER_FPS", 10.634)
fps_render_b = wb.get("RENDER_FPS", 17.076)
fps_render_c = wc.get("RENDER_FPS", 26.359)

fps_eff_a = wa.get("USER_EFFECTIVE_FPS", 9.885)
fps_eff_b = wb.get("USER_EFFECTIVE_FPS", 15.283)
fps_eff_c = wc.get("USER_EFFECTIVE_FPS", 22.183)

wall_a = wa.get("TOTAL_FROM_EXPORT_START_ms", 114411.7) / 1000.0
wall_b = wb.get("TOTAL_FROM_EXPORT_START_ms", 74005.9) / 1000.0
wall_c = wc.get("TOTAL_FROM_EXPORT_START_ms", 50985.9) / 1000.0

print(f"{'RENDER FPS':<26} | {fps_render_a:14.3f} | {fps_render_b:14.3f} | {fps_render_c:14.3f} | +{fps_render_c - fps_render_a:5.3f} (+{(fps_render_c-fps_render_a)/fps_render_a*100:.1f}%)")
print(f"{'USER EFFECTIVE FPS':<26} | {fps_eff_a:14.3f} | {fps_eff_b:14.3f} | {fps_eff_c:14.3f} | +{fps_eff_c - fps_eff_a:5.3f} (+{(fps_eff_c-fps_eff_a)/fps_eff_a*100:.1f}%)")
print(f"{'Total Wall Clock':<26} | {wall_a:11.3f} s  | {wall_b:11.3f} s  | {wall_c:11.3f} s  | -{wall_a - wall_c:6.3f} s (-{(wall_a-wall_c)/wall_a*100:.1f}%)")
