import json
import statistics
from pathlib import Path

sum_p = Path('Raporty/etap8o_artifacts/etap8o_benchmark_summary.json')
with open(sum_p) as f:
    data = json.load(f)

print('=== ETAP 8O BENCHMARK ANALYSIS ===')
for group in ['reference', 'precomputed']:
    print(f'\n--- {group.upper()} (900 frames) ---')
    fps_list = []
    wall_list = []
    telem_med_list = []
    telem_p95_list = []
    compose_med_list = []
    above_med_list = []
    map_med_list = []
    build_ms_list = []
    
    for r in data[group]:
        prof = r.get('profile', {})
        wall = r['wall_s']
        wall_list.append(wall)
        
        frames = prof.get('frame_accounting', {}).get('native_processed', 900)
        fps = frames / wall
        fps_list.append(fps)
        
        timings = prof.get('timings', {})
        t_data = timings.get('Telemetry/frame_data', {})
        telem_med = t_data.get('median_ms', 0.0)
        telem_p95 = t_data.get('p95_ms', 0.0)
        telem_med_list.append(telem_med)
        telem_p95_list.append(telem_p95)
        
        compose_med = timings.get('compose_overlay', {}).get('median_ms', 0.0)
        above_med = timings.get('above_total', {}).get('median_ms', 0.0)
        map_med = timings.get('map_cpu_upload', {}).get('median_ms', 0.0)
        
        compose_med_list.append(compose_med)
        above_med_list.append(above_med)
        map_med_list.append(map_med)
        
        e8o = prof.get('etap8o', {})
        stats = e8o.get('precomputed_stats')
        build_ms = stats.get('build_ms', 0.0) if stats else 0.0
        build_ms_list.append(build_ms)
        
        print(f"{r['run_name']}: Wall={wall:.3f}s, FPS={fps:.3f}, Telem_med={telem_med:.3f}ms (p95={telem_p95:.3f}ms), Compose={compose_med:.3f}ms, Above={above_med:.3f}ms, Map={map_med:.3f}ms, Build={build_ms:.1f}ms")
        
    print(f"MEDIAN {group.upper()}: Wall={statistics.median(wall_list):.3f}s, FPS={statistics.median(fps_list):.3f}, Telem_med={statistics.median(telem_med_list):.3f}ms, Telem_p95={statistics.median(telem_p95_list):.3f}ms, Compose={statistics.median(compose_med_list):.3f}ms, Above={statistics.median(above_med_list):.3f}ms, Map={statistics.median(map_med_list):.3f}ms, Build={statistics.median(build_ms_list):.1f}ms")

# Full 5395
r_full = data.get('full_5395')
if r_full:
    print(f"\n--- FULL MATERIAL (5395 frames, PRECOMPUTED) ---")
    prof = r_full.get('profile', {})
    wall = r_full['wall_s']
    fps = 5395 / wall
    timings = prof.get('timings', {})
    t_data = timings.get('Telemetry/frame_data', {})
    telem_med = t_data.get('median_ms', 0.0)
    telem_p95 = t_data.get('p95_ms', 0.0)
    compose_med = timings.get('compose_overlay', {}).get('median_ms', 0.0)
    above_med = timings.get('above_total', {}).get('median_ms', 0.0)
    map_med = timings.get('map_cpu_upload', {}).get('median_ms', 0.0)
    e8o = prof.get('etap8o', {})
    stats = e8o.get('precomputed_stats')
    build_ms = stats.get('build_ms', 0.0) if stats else 0.0
    mem_kib = stats.get('memory_bytes', 0) / 1024.0 if stats else 0.0
    print(f"Full 5395: Wall={wall:.3f}s, TRUE FPS={fps:.3f}, Telem_med={telem_med:.3f}ms (p95={telem_p95:.3f}ms), Compose={compose_med:.3f}ms, Above={above_med:.3f}ms, Map={map_med:.3f}ms, Build={build_ms/1000.0:.2f}s, Cache Mem={mem_kib:.1f} KiB")
