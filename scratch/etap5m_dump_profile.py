"""ETAP 5M — dump profiling-run profile (timings + overlay per-widget breakdown)."""
import json

d = json.load(open(r"Raporty/AMD_ETAP5G/5m_profile.mp4.amd_profile.json", encoding="utf-8"))
t = d["timings"]
print("=== TRUE FPS / wall (profiling run, NOT baseline) ===")
print(f"  true_fps={d['true_fps']:.3f} wall={d['total_wall_clock_s']:.3f}s")

print("\n=== NATIVE/GPU TIMINGS (median ms) ===")
native_keys = [
    "Decode/pipe wait", "MF ReadSample/decode availability", "MF decoder surface acquisition",
    "Decoder surface GPU copy", "Native HUD CPU copy", "HUD texture upload",
    "NV12 staging memcpy", "BlendRGBAToNV12", "CopyResource submission",
    "VideoProcessor CPU submit", "VideoProcessor GPU completion",
    "GPU wait/synchronization", "AMF submit/backpressure", "AMF QueryOutput",
    "Packet write", "Python->native bridge",
]
for k in native_keys:
    s = t.get(k)
    if s:
        print(f"  {k:34s} avg={s['avg_ms']:7.3f} med={s['median_ms']:7.3f} p95={s['p95_ms']:7.3f} p99={s['p99_ms']:7.3f}")

print("\n=== CPU/OVERLAY STAGES (median ms) ===")
cpu_keys = [
    "Telemetry/frame_data", "compose_overlay", "HUD dirty bbox", "HUD dirty extract",
    "PIL/buffer preparation", "update_hud", "map_cpu_upload", "gauge_tobytes",
    "gauge_upload", "chart_dynamic_tobytes", "chart_dynamic_upload",
    "GPU chart blend submit", "GPU gauge blend submit", "GPU map upload (native)",
    "GPU map resize+blend submit",
]
for k in cpu_keys:
    s = t.get(k)
    if s:
        print(f"  {k:34s} avg={s['avg_ms']:7.3f} med={s['median_ms']:7.3f} p95={s['p95_ms']:7.3f} p99={s['p99_ms']:7.3f}")

print("\n=== OVERLAY PROFILER (etap5a) — per-widget CPU breakdown ===")
p = d.get("etap5a", {})
print(f"  enabled={p.get('enabled')} frames={p.get('frames')}")
metrics = p.get("metrics", {})
if metrics:
    keys = sorted(metrics.keys())
    print(f"  {'metric':48s} med     p95     avg")
    for k in keys:
        m = metrics[k]
        print(f"  {k:48s} {m['median_ms']:7.3f} {m['p95_ms']:7.3f} {m['avg_ms']:7.3f}  calls/f={m['avg_calls_per_frame']:.2f}")
