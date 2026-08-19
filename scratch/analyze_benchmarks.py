import json
import statistics
from pathlib import Path

sum_p = Path('Raporty/etap8n_artifacts/etap8n_benchmark_summary.json')
with open(sum_p) as f:
    data = json.load(f)

print('=== BENCHMARK SUMMARY ===')
for group in ['before', 'after']:
    print(f'\n--- {group.upper()} RUNS ---')
    fps_list = []
    wall_list = []
    crop_med_list = []
    crop_p95_list = []
    compose_med_list = []
    total_above_med_list = []
    cand_pixels_list = []
    scanned_pixels_list = []
    uploaded_pixels_list = []
    uploaded_bytes_list = []
    
    for r in data[group]:
        prof = r.get('profile', {})
        wall = r['wall_s']
        wall_list.append(wall)
        
        frames = prof.get('frame_accounting', {}).get('native_processed', 900)
        fps = frames / wall
        fps_list.append(fps)
        
        e8c = prof.get('etap8c', {})
        e8n = prof.get('etap8n', {})
        
        stages = prof.get('stages', {})
        # Check timing summary directly if present
        timings = prof.get('timing_summary', {})
        
        crop_med = timings.get('above_bbox_crop', {}).get('median_ms', 0.0)
        crop_p95 = timings.get('above_bbox_crop', {}).get('p95_ms', 0.0)
        compose_med = timings.get('above_compose', {}).get('median_ms', 0.0)
        total_above_med = timings.get('above_total', {}).get('median_ms', 0.0)
        
        crop_med_list.append(crop_med)
        crop_p95_list.append(crop_p95)
        compose_med_list.append(compose_med)
        total_above_med_list.append(total_above_med)
        
        cand_pix = e8c.get('candidate_pixels', {}).get('median', 0) if e8c else 0
        up_bytes = e8c.get('above_upload_bytes_per_frame', 0) if e8c else 0
        cand_pixels_list.append(cand_pix)
        uploaded_bytes_list.append(up_bytes)
        
        print(f"{r['run_name']}: Wall={wall:.3f}s, FPS={fps:.3f}, crop_med={crop_med:.3f}ms (p95={crop_p95:.3f}ms), compose_med={compose_med:.3f}ms, above_total_med={total_above_med:.3f}ms, cand_pixels={cand_pix:,.0f}, up_bytes/f={up_bytes:,.0f} B")

    print(f"MEDIAN {group.upper()}: Wall={statistics.median(wall_list):.3f}s, FPS={statistics.median(fps_list):.3f}, crop_med={statistics.median(crop_med_list):.3f}ms, crop_p95={statistics.median(crop_p95_list):.3f}ms, compose_med={statistics.median(compose_med_list):.3f}ms, above_total_med={statistics.median(total_above_med_list):.3f}ms, cand_pixels={statistics.median(cand_pixels_list):,.0f}, up_bytes={statistics.median(uploaded_bytes_list):,.0f} B")
