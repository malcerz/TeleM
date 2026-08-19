import json
import statistics
from pathlib import Path

p_bef = Path('Raporty/etap8p_b_artifacts/etap8q_before_baseline.json')
p_aft = Path('Raporty/etap8p_b_artifacts/etap8q_after_benchmarks.json')

with open(p_bef) as f:
    bef_data = json.load(f)
with open(p_aft) as f:
    aft_data = json.load(f)

print('=== ETAP 8Q REAL BENCHMARK COMPARISON ===\n')

def extract_metrics(run_list):
    above_meds, above_p95s, above_totals = [], [], []
    render_walls, total_walls = [], []
    render_fpss, eff_fpss = [], []
    for r in run_list:
        prof = r['profile']
        t = prof['timings']
        e8p = prof['etap8p_a']
        above_meds.append(t['above_compose']['median_ms'])
        above_p95s.append(t['above_compose']['p95_ms'])
        above_totals.append(t['above_total']['median_ms'])
        render_walls.append(e8p['video_render_wall_ms'])
        total_walls.append(e8p['total_from_export_start_ms'])
        render_fpss.append(e8p['render_fps'])
        eff_fpss.append(e8p['effective_fps'])
        print(f"  {r['run_name']}: above_compose={above_meds[-1]:.3f}ms (p95={above_p95s[-1]:.3f}ms), above_total={above_totals[-1]:.3f}ms, RenderWall={render_walls[-1]/1000.0:.3f}s, TotalWall={total_walls[-1]/1000.0:.3f}s, RenderFPS={render_fpss[-1]:.3f}, EffectiveFPS={eff_fpss[-1]:.3f}")
    return {
        "above_compose_med": statistics.median(above_meds),
        "above_compose_p95": statistics.median(above_p95s),
        "above_total": statistics.median(above_totals),
        "render_wall": statistics.median(render_walls),
        "total_wall": statistics.median(total_walls),
        "render_fps": statistics.median(render_fpss),
        "eff_fps": statistics.median(eff_fpss),
    }

print('--- 3 x BEFORE (1131 frames 4K, cache OFF) ---')
m_bef = extract_metrics(bef_data)
print(f"  MEDIAN: above_compose={m_bef['above_compose_med']:.3f}ms, RenderFPS={m_bef['render_fps']:.3f}, TotalWall={m_bef['total_wall']/1000.0:.3f}s\n")

print('--- 3 x AFTER (1131 frames 4K, cache ON) ---')
m_aft = extract_metrics(aft_data['after_1131'])
print(f"  MEDIAN: above_compose={m_aft['above_compose_med']:.3f}ms, RenderFPS={m_aft['render_fps']:.3f}, TotalWall={m_aft['total_wall']/1000.0:.3f}s\n")

speedup_above = m_bef['above_compose_med'] / m_aft['above_compose_med']
fps_gain = m_aft['render_fps'] - m_bef['render_fps']
fps_gain_pct = (fps_gain / m_bef['render_fps']) * 100.0
time_saved_s = (m_bef['total_wall'] - m_aft['total_wall']) / 1000.0

print(f"=== 1131-FRAME COMPARISON ===")
print(f"  above_compose: {m_bef['above_compose_med']:.3f} ms -> {m_aft['above_compose_med']:.3f} ms ({speedup_above:.1f}x faster!)")
print(f"  Render FPS:    {m_bef['render_fps']:.3f} FPS -> {m_aft['render_fps']:.3f} FPS (+{fps_gain:.3f} FPS / +{fps_gain_pct:.2f}%)")
print(f"  Total Wall:    {m_bef['total_wall']/1000.0:.3f} s -> {m_aft['total_wall']/1000.0:.3f} s (Saved {time_saved_s:.3f} s / -{(time_saved_s / (m_bef['total_wall']/1000.0))*100.0:.2f}%)")

r_full = aft_data.get('full_5395')
if r_full:
    print('\n--- FULL MATERIAL (5395 frames 4K, GX030120.MP4, FAST + CACHE ON) ---')
    prof = r_full['profile']
    t = prof['timings']
    e8p = prof['etap8p_a']
    print(f"  above_compose: {t['above_compose']['median_ms']:.3f} ms (p95={t['above_compose']['p95_ms']:.3f} ms)")
    print(f"  Render Wall:   {e8p['video_render_wall_ms']/1000.0:.3f} s")
    print(f"  Render FPS:    {e8p['render_fps']:.3f} FPS (was ~30.7 FPS in 8P-B, was ~15 FPS in 8O)")
    print(f"  Total Wall:    {e8p['total_from_export_start_ms']/1000.0:.3f} s (was 182.565 s in 8P-B -> SAVED {182.565 - e8p['total_from_export_start_ms']/1000.0:.2f} s!)")
    print(f"  Effective FPS: {e8p['effective_fps']:.3f} FPS")
