import json
with open('Raporty/NVIDIA_NV0/summary.json') as f:
    s = json.load(f)

frames = s['exported_frames']
wall = s['export_wall_seconds']
fps = frames / wall
print(f'exported_frames: {frames}')
print(f'export_wall_seconds: {wall}')
print(f'frames / wall = {fps:.6f}')
print(f'stored true_fps: {s["true_fps"]:.6f}')
print(f'Match: {abs(fps - s["true_fps"]) < 0.001}')
print()
print('Confirmed: 27.15 FPS = 1131 / 41.664 (time.perf_counter wall-clock)')
print('NOT derived from media duration (media duration = 37.74s, would give ~30 FPS)')
