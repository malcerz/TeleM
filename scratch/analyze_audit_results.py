"""Print a compact audit summary from Raporty/AMD_RENDER_PATH_AUDIT/audit_summary.json."""
import json, sys

p = r"Raporty/AMD_RENDER_PATH_AUDIT/audit_summary.json"
data = json.load(open(p, encoding="utf-8"))
order = [
    "test_A_1080p_full", "test_B_4k_full", "test_C_1080p_nohud", "test_D_4k_nohud",
    "abl_full_720p", "abl_none_720p", "abl_text_720p", "abl_gauge_720p", "abl_chart_720p",
    "abl_map_720p", "abl_gauge_chart_720p", "abl_map_gauge_chart_720p",
    "map_cpu_reference_720p", "decode_cpu_reference_720p",
    "amf_submit_no_mux_720p", "amf_bypass_720p", "telemetry_reference_720p",
    "res_720p_full", "res_1440p_full", "soak_720p_600f", "sysprobe_1080p_300f",
    "alloc_tracemalloc_720p",
]
by = {r["name"]: r for r in data}
stages = ["MF ReadSample/decode availability", "Telemetry/frame_data", "compose_overlay",
          "above_compose", "above_bbox_crop", "above_region_to_bytes", "above_region_upload",
          "above_total", "map_cpu_upload", "HUD dirty extract", "PIL/buffer preparation",
          "update_hud", "VideoProcessor CPU submit", "VideoProcessor GPU completion",
          "GPU wait/synchronization", "AMF submit/backpressure", "AMF QueryOutput",
          "Packet write", "Audio mux", "producer_prepare", "consumer_upload",
          "consumer_native_call", "pipeline_total"]

def med(r, k):
    t = r.get("profile", {}).get("timings", {})
    v = t.get(k)
    return v.get("med") if isinstance(v, dict) else None

print("=" * 160)
print(f"{'case':28} {'res':12} {'fr':5} {'rFPS':>8} {'tFPS':>7} {'muxms':>7} | " +
      " | ".join(f"{s.split()[0][:6]:>7}" for s in stages))
print("=" * 160)
for name in order:
    if name not in by:
        continue
    r = by[name]
    res = f"{r['width']}x{r['height']}"
    fr = r["frames"]
    p = r.get("profile", {})
    row = [f"{name:28}", f"{res:12}", f"{fr:5}",
           f"{p.get('render_fps') or 0:8.2f}", f"{p.get('true_fps') or 0:7.2f}",
           f"{p.get('mux_wall_ms') or 0:7.1f}"]
    for s in stages:
        v = med(r, s)
        row.append(f"{(v if v is not None else 0.0):7.2f}")
    print(" | ".join(row))
print("=" * 160)

# system metrics table
print("\n--- SYSTEM METRICS (sampler avg) ---")
print(f"{'case':28} {'cpu':>6} {'g3d':>6} {'gdec':>6} {'genc':>6} {'ramMB':>8} {'vramDed':>8} {'vramShr':>8}")
for name in order:
    if name not in by:
        continue
    r = by[name]
    s = r.get("system", {})
    def g(k):
        v = s.get(k)
        return v.get("avg") if isinstance(v, dict) and v.get("avg") is not None else None
    print(f"{name:28} {g('cpu_total') or 0:6.1f} {g('gpu_3d') or 0:6.1f} {g('gpu_decode') or 0:6.1f} "
          f"{g('gpu_encode') or 0:6.1f} {g('ram_used_mb') or 0:8.0f} {g('vram_ded_mb') or 0:8.0f} {g('vram_shared_mb') or 0:8.0f}")
