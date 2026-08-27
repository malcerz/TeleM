import json

cpu = json.load(open('scratch/etap2g_bench/lean_cpu_300f.mp4.amd_profile.json', encoding='utf-8'))
gpu = json.load(open('scratch/etap2g_bench/lean_gpu_300f.mp4.amd_profile.json', encoding='utf-8'))

print('=' * 85)
print(f"{'Metric':<32} {'CPU Tight (2F-B)':<18} {'GPU Lean (2G)':<18} {'Delta':<16}")
print('-' * 85)

render_cpu = cpu.get('etap8p_a', {}).get('render_fps', 0.0)
render_gpu = gpu.get('etap8p_a', {}).get('render_fps', 0.0)
d_r = render_gpu - render_cpu
pct_r = (d_r / render_cpu) * 100.0 if render_cpu else 0
print(f"{'RENDER FPS':<32} {render_cpu:<18.3f} {render_gpu:<18.3f} {d_r:+.3f} ({pct_r:+.1f}%)")

eff_cpu = cpu.get('etap8p_a', {}).get('effective_fps', 0.0)
eff_gpu = gpu.get('etap8p_a', {}).get('effective_fps', 0.0)
d_e = eff_gpu - eff_cpu
pct_e = (d_e / eff_cpu) * 100.0 if eff_cpu else 0
print(f"{'USER EFFECTIVE FPS':<32} {eff_cpu:<18.3f} {eff_gpu:<18.3f} {d_e:+.3f} ({pct_e:+.1f}%)")

timings = [
    ('above_compose (ms)', 'above_compose'),
    ('above_total (ms)', 'above_total'),
    ('producer_prepare (ms)', 'producer_prepare'),
    ('consumer_native_call (ms)', 'consumer_native_call'),
    ('pipeline_total (ms)', 'pipeline_total'),
]

for label, key in timings:
    c_avg = cpu.get('timings', {}).get(key, {}).get('avg_ms', 0.0)
    g_avg = gpu.get('timings', {}).get(key, {}).get('avg_ms', 0.0)
    d = g_avg - c_avg
    pct = (d / c_avg) * 100.0 if c_avg else 0
    print(f"{label:<32} {c_avg:<18.3f} {g_avg:<18.3f} {d:+.3f} ms ({pct:+.1f}%)")

print('=' * 85)
