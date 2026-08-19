import json
import statistics
from pathlib import Path

p = Path('Raporty/etap8p_b_artifacts/etap8q_before_baseline.json')
with open(p) as f:
    data = json.load(f)

above_meds, above_p95s, above_totals = [], [], []
render_walls, total_walls = [], []
render_fpss, eff_fpss = [], []

for r in data:
    prof = r['profile']
    t = prof['timings']
    e8p = prof['etap8p_a']
    
    above_med = t['above_compose']['median_ms']
    above_p95 = t['above_compose']['p95_ms']
    above_tot = t['above_total']['median_ms']
    rw = e8p['video_render_wall_ms']
    tot = e8p['total_from_export_start_ms']
    rfps = e8p['render_fps']
    efps = e8p['effective_fps']
    
    above_meds.append(above_med)
    above_p95s.append(above_p95)
    above_totals.append(above_tot)
    render_walls.append(rw)
    total_walls.append(tot)
    render_fpss.append(rfps)
    eff_fpss.append(efps)
    
    print(f"{r['run_name']}: above_compose_med={above_med:.3f}ms, p95={above_p95:.3f}ms, above_total={above_tot:.3f}ms, render_wall={rw/1000.0:.3f}s, total_wall={tot/1000.0:.3f}s, render_fps={rfps:.3f}, eff_fps={efps:.3f}")

print(f"\nMEDIAN BEFORE: above_compose_med={statistics.median(above_meds):.3f}ms, p95={statistics.median(above_p95s):.3f}ms, above_total={statistics.median(above_totals):.3f}ms, render_wall={statistics.median(render_walls)/1000.0:.3f}s, total_wall={statistics.median(total_walls)/1000.0:.3f}s, render_fps={statistics.median(render_fpss):.3f}, eff_fps={statistics.median(eff_fpss):.3f}")
