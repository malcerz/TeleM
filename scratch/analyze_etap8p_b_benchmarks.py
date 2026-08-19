import json
import statistics
from pathlib import Path

sum_p = Path('Raporty/etap8p_b_artifacts/etap8p_b_benchmark_summary.json')
with open(sum_p) as f:
    data = json.load(f)

print('=== ETAP 8P-B REAL BENCHMARK ANALYSIS ===\n')

for group in ['reference_1131', 'fast_precomputed_1131']:
    print(f'--- {group.upper()} (1131 frames, 4K) ---')
    build_list = []
    delay_first_list = []
    render_wall_list = []
    mux_list = []
    total_wall_list = []
    render_fps_list = []
    effective_fps_list = []
    telem_med_list = []
    
    for r in data[group]:
        prof = r.get('profile', {})
        e8p = prof.get('etap8p_a', {})
        b_ms = e8p.get('precompute_build_ms', 0.0)
        d_ms = e8p.get('delay_export_to_first_frame_ms', 0.0)
        rw_ms = e8p.get('video_render_wall_ms', 0.0)
        m_ms = e8p.get('mux_wall_ms', 0.0)
        tot_ms = e8p.get('total_from_export_start_ms', 0.0)
        rfps = e8p.get('render_fps', 0.0)
        efps = e8p.get('effective_fps', 0.0)
        t_med = prof.get('timings', {}).get('Telemetry/frame_data', {}).get('median_ms', 0.0)
        
        build_list.append(b_ms)
        delay_first_list.append(d_ms)
        render_wall_list.append(rw_ms)
        mux_list.append(m_ms)
        total_wall_list.append(tot_ms)
        render_fps_list.append(rfps)
        effective_fps_list.append(efps)
        telem_med_list.append(t_med)
        
        print(f"  {r['run_name']}: Build={b_ms:.1f}ms, Delay1st={d_ms:.1f}ms, RenderWall={rw_ms/1000.0:.3f}s, Mux={m_ms/1000.0:.3f}s, Total={tot_ms/1000.0:.3f}s, RenderFPS={rfps:.3f}, EffectiveFPS={efps:.3f}, TelemMed={t_med:.3f}ms")
        
    print(f"  MEDIAN: Build={statistics.median(build_list):.1f}ms ({statistics.median(build_list)/1000.0:.3f}s), Delay1st={statistics.median(delay_first_list):.1f}ms, RenderWall={statistics.median(render_wall_list)/1000.0:.3f}s, Mux={statistics.median(mux_list)/1000.0:.3f}s, TotalUserWall={statistics.median(total_wall_list)/1000.0:.3f}s, RenderFPS={statistics.median(render_fps_list):.3f}, EffectiveFPS={statistics.median(effective_fps_list):.3f}, TelemMed={statistics.median(telem_med_list):.3f}ms\n")

r_full = data.get('full_5395')
if r_full:
    print('--- FULL MATERIAL (5395 frames, 4K, FAST PRECOMPUTED) ---')
    prof = r_full.get('profile', {})
    e8p = prof.get('etap8p_a', {})
    b_ms = e8p.get('precompute_build_ms', 0.0)
    d_ms = e8p.get('delay_export_to_first_frame_ms', 0.0)
    rw_ms = e8p.get('video_render_wall_ms', 0.0)
    m_ms = e8p.get('mux_wall_ms', 0.0)
    tot_ms = e8p.get('total_from_export_start_ms', 0.0)
    rfps = e8p.get('render_fps', 0.0)
    efps = e8p.get('effective_fps', 0.0)
    t_med = prof.get('timings', {}).get('Telemetry/frame_data', {}).get('median_ms', 0.0)
    print(f"  Build={b_ms:.1f}ms ({b_ms/1000.0:.3f}s), Delay1st={d_ms:.1f}ms, RenderWall={rw_ms/1000.0:.3f}s, Mux={m_ms/1000.0:.3f}s, TotalUserWall={tot_ms/1000.0:.3f}s, RenderFPS={rfps:.3f}, EffectiveFPS={efps:.3f}, TelemMed={t_med:.3f}ms")
