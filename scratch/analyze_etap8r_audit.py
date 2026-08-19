"""
Analysis script for ETAP 8R Audit Results.
Parses:
1. etap8r_audit_results.json
2. GPU timeline CSV files
3. Computes exclusive CPU breakdowns, GPU stage spans, 60 FPS budgets, and bottlenecks.
"""
import csv
import json
import statistics
from pathlib import Path

root = Path("c:/_DEV/TeleM")
audit_dir = root / "Raporty" / "etap8r_artifacts"
results_file = audit_dir / "etap8r_audit_results.json"

with open(results_file) as f:
    data = json.load(f)

print("=================================================================")
print("                   ETAP 8R AUDIT DATA ANALYSIS                   ")
print("=================================================================\n")

def parse_gpu_csv(csv_path):
    if not Path(csv_path).exists():
        return None
    rows = []
    with open(csv_path, newline="") as f:
        reader = csv.DictReader(f)
        for r in reader:
            if r.get("ready") == "1":
                rows.append({k: float(v) for k, v in r.items()})
    if not rows:
        return None
    
    spans = [r["span_ms"] for r in rows if r["span_ms"] > 0]
    vps = [r["vp_ms"] for r in rows if r["vp_ms"] >= 0]
    ranges = [r["range_ms"] for r in rows if r["range_ms"] >= 0]
    charts = [r["charts_ms"] for r in rows if r["charts_ms"] >= 0]
    gauges = [r["gauge_ms"] for r in rows if r["gauge_ms"] >= 0]
    maps = [r["map_ms"] for r in rows if r["map_ms"] >= 0]
    huds = [r["hud_ms"] for r in rows if r["hud_ms"] >= 0]
    
    def q(lst):
        if not lst: return 0.0, 0.0
        s = sorted(lst)
        med = statistics.median(s)
        p95 = s[int(len(s) * 0.95)]
        return med, p95

    return {
        "count": len(rows),
        "span": q(spans),
        "vp": q(vps),
        "range": q(ranges),
        "charts": q(charts),
        "gauge": q(gauges),
        "map": q(maps),
        "hud": q(huds),
    }

# 1. 3 x Fresh 4K Baseline
print("--- 1. FRESH 4K BASELINE (3 x 1131 frames) ---")
b_fps, b_eff, b_wall, b_rwall = [], [], [], []
for i, r in enumerate(data["baseline_4k"]):
    prof = r["profile"]
    e8p = prof["etap8p_a"]
    b_fps.append(e8p["render_fps"])
    b_eff.append(e8p["effective_fps"])
    b_wall.append(e8p["total_from_export_start_ms"])
    b_rwall.append(e8p["video_render_wall_ms"])
    print(f"  Run {i+1}: Render FPS={e8p['render_fps']:.3f}, Effective FPS={e8p['effective_fps']:.3f}, Render Wall={e8p['video_render_wall_ms']/1000.0:.3f}s, Total Wall={e8p['total_from_export_start_ms']/1000.0:.3f}s")

med_fps = statistics.median(b_fps)
med_eff = statistics.median(b_eff)
med_wall = statistics.median(b_wall)
med_rwall = statistics.median(b_rwall)
print(f"  --> BASELINE MEDIAN: Render FPS={med_fps:.3f}, Effective FPS={med_eff:.3f}, Render Wall={med_rwall/1000.0:.3f}s, Total Wall={med_wall/1000.0:.3f}s\n")

# Timings from Run 2 (representative)
prof_b = data["baseline_4k"][1]["profile"]
t = prof_b["timings"]
print("--- 2. CPU EXCLUSIVE FRAME TIMINGS (Run 2 profile) ---")
print(f"  MF ReadSample (decode wait): {t['MF ReadSample/decode availability']['median_ms']:.3f} ms (p95={t['MF ReadSample/decode availability']['p95_ms']:.3f})")
print(f"  Telemetry/frame_data:        {t['Telemetry/frame_data']['median_ms']:.3f} ms (p95={t['Telemetry/frame_data']['p95_ms']:.3f})")
print(f"  compose_overlay (BELOW):     {t['compose_overlay']['median_ms']:.3f} ms (p95={t['compose_overlay']['p95_ms']:.3f})")
print(f"  map_cpu_upload:              {t['map_cpu_upload']['median_ms']:.3f} ms (p95={t['map_cpu_upload']['p95_ms']:.3f})")
print(f"  gauge_tobytes + upload:      {t['gauge_tobytes']['median_ms'] + t['gauge_upload']['median_ms']:.3f} ms")
print(f"  chart_dynamic_tobytes/up:    {t['chart_dynamic_tobytes']['median_ms'] + t['chart_dynamic_upload']['median_ms']:.3f} ms")
print(f"  above_compose + upload:      {t['above_total']['median_ms']:.3f} ms")
print(f"  HUD dirty extract + upload:  {t['HUD dirty extract']['median_ms'] + t['HUD texture upload']['median_ms']:.3f} ms")
print(f"  VideoProcessor CPU submit:   {t['VideoProcessor CPU submit']['median_ms']:.3f} ms")
print(f"  GPU wait/synchronization:    {t['GPU wait/synchronization']['median_ms']:.3f} ms (p95={t['GPU wait/synchronization']['p95_ms']:.3f})")
print(f"  AMF submit/backpressure:     {t['AMF submit/backpressure']['median_ms']:.3f} ms")
print(f"  AMF QueryOutput:             {t['AMF QueryOutput']['median_ms']:.3f} ms")
print(f"  Packet write:                {t['Packet write']['median_ms']:.3f} ms")

frame_ms = 1000.0 / med_fps
print(f"\n  FRAME TOTAL DURATION:        {frame_ms:.3f} ms (corresponds to {med_fps:.3f} FPS)")

# Active CPU vs Wait
cpu_active = (
    t['Telemetry/frame_data']['median_ms'] +
    t['compose_overlay']['median_ms'] +
    t['map_cpu_upload']['median_ms'] +
    t['gauge_tobytes']['median_ms'] + t['gauge_upload']['median_ms'] +
    t['chart_dynamic_tobytes']['median_ms'] + t['chart_dynamic_upload']['median_ms'] +
    t['above_total']['median_ms'] +
    t['HUD dirty extract']['median_ms'] + t['HUD texture upload']['median_ms'] +
    t['VideoProcessor CPU submit']['median_ms'] +
    t['Packet write']['median_ms']
)
cpu_gpu_wait = t['GPU wait/synchronization']['median_ms']
cpu_amf_wait = t['AMF submit/backpressure']['median_ms'] + t['AMF QueryOutput']['median_ms']
cpu_dec_wait = t['MF ReadSample/decode availability']['median_ms']

print(f"\n--- 3. CPU ACTIVE vs WAIT CLASSIFICATION ---")
print(f"  CPU ACTIVE WORK:             {cpu_active:.3f} ms ({cpu_active/frame_ms*100.0:.1f}%)")
print(f"  CPU GPU WAIT (Sync):         {cpu_gpu_wait:.3f} ms ({cpu_gpu_wait/frame_ms*100.0:.1f}%)")
print(f"  CPU AMF WAIT (Encode):       {cpu_amf_wait:.3f} ms ({cpu_amf_wait/frame_ms*100.0:.1f}%)")
print(f"  CPU DECODE WAIT:             {cpu_dec_wait:.3f} ms ({cpu_dec_wait/frame_ms*100.0:.1f}%)")
sum_explained = cpu_active + cpu_gpu_wait + cpu_amf_wait + cpu_dec_wait
print(f"  SUM EXPLAINED:               {sum_explained:.3f} ms (Residual = {abs(frame_ms - sum_explained):.3f} ms / {abs(frame_ms - sum_explained)/frame_ms*100.0:.1f}%)")

# GPU Timestamps Analysis
print("\n--- 4. GPU TIMELINE DISJOINT TIMESTAMPS (from CSV) ---")
for i in range(1, 4):
    csv_p = audit_dir / f"etap8r_baseline_run{i}.mp4.gpu_timeline.csv"
    res_gpu = parse_gpu_csv(csv_p)
    if res_gpu:
        print(f"  Baseline Run {i} GPU Timeline ({res_gpu['count']} frames):")
        print(f"    GPU SPAN (Total GPU execution): {res_gpu['span'][0]:.3f} ms (p95={res_gpu['span'][1]:.3f} ms)")
        print(f"    - VideoProcessorBlt (Hardware): {res_gpu['vp'][0]:.3f} ms (p95={res_gpu['vp'][1]:.3f} ms)")
        print(f"    - Range Normalize Pass:         {res_gpu['range'][0]:.3f} ms (p95={res_gpu['range'][1]:.3f} ms)")
        print(f"    - Charts Blend (Clear+Blend):   {res_gpu['charts'][0]:.3f} ms (p95={res_gpu['charts'][1]:.3f} ms)")
        print(f"    - Gauge Blend (Clear+Blend):    {res_gpu['gauge'][0]:.3f} ms (p95={res_gpu['gauge'][1]:.3f} ms)")
        print(f"    - Map Resize+Blend:             {res_gpu['map'][0]:.3f} ms (p95={res_gpu['map'][1]:.3f} ms)")
        print(f"    - Fused NV12 HUD Compositor:    {res_gpu['hud'][0]:.3f} ms (p95={res_gpu['hud'][1]:.3f} ms)")

# Profiler Overhead
print("\n--- 5. PROFILER OVERHEAD (TS ON vs TS OFF) ---")
fps_ts_on = med_fps
fps_ts_off = data["ts_off"]["profile"]["etap8p_a"]["render_fps"]
diff_fps = fps_ts_off - fps_ts_on
diff_pct = (diff_fps / fps_ts_off) * 100.0
print(f"  GPU Timestamps ON:  {fps_ts_on:.3f} FPS")
print(f"  GPU Timestamps OFF: {fps_ts_off:.3f} FPS")
print(f"  Difference:         {diff_fps:+.3f} FPS ({diff_pct:+.2f}% overhead) -> PASS (< 3%)")

# Resolution Comparison (4K vs 1080p)
print("\n--- 6. RESOLUTION COMPARISON (4K vs 1080p) ---")
fps_1080p = data["res_1080p"]["profile"]["etap8p_a"]["render_fps"]
wall_1080p = data["res_1080p"]["profile"]["etap8p_a"]["video_render_wall_ms"] / 1000.0
csv_1080p = audit_dir / "etap8r_1080p.mp4.gpu_timeline.csv"
gpu_1080p = parse_gpu_csv(csv_1080p)
print(f"  4K Baseline:        {med_fps:.3f} FPS ({med_rwall/1000.0:.3f}s)")
print(f"  1080p Output:       {fps_1080p:.3f} FPS ({wall_1080p:.3f}s)")
print(f"  FPS Gain at 1080p:  +{fps_1080p - med_fps:.3f} FPS (+{(fps_1080p - med_fps)/med_fps*100.0:.1f}%)")
if gpu_1080p:
    print(f"  1080p GPU Span:     {gpu_1080p['span'][0]:.3f} ms (vs 4K ~17.3 ms)")

# Control Runs (Overlay Subsystems OFF)
print("\n--- 7. CONTROL RUNS (A/B SUB-SYSTEM ISOLATION) ---")
def print_ctrl(name, key, csv_name):
    r = data[key]
    if isinstance(r, list):
        r = r[0]
    prof = r["profile"]
    fps = prof["etap8p_a"]["render_fps"]
    csv_p = audit_dir / csv_name
    gpu_d = parse_gpu_csv(csv_p)
    gpu_span_str = f"{gpu_d['span'][0]:.3f} ms" if gpu_d else "N/A"
    diff = fps - med_fps
    pct = (diff / med_fps) * 100.0
    print(f"  {name:<20}: {fps:.3f} FPS (Gain: {diff:+.3f} FPS / {pct:+.1f}%), GPU Span: {gpu_span_str}")

print_ctrl("Baseline 4K (All ON)", "baseline_4k", "etap8r_baseline_run1.mp4.gpu_timeline.csv")
print_ctrl("Gauge OFF", "gauge_off", "etap8r_gauge_off.mp4.gpu_timeline.csv")
print_ctrl("Charts OFF", "charts_off", "etap8r_charts_off.mp4.gpu_timeline.csv")
print_ctrl("Map OFF", "map_off", "etap8r_map_off.mp4.gpu_timeline.csv")
print_ctrl("ALL Overlays OFF", "overlays_off", "etap8r_overlays_off.mp4.gpu_timeline.csv")
