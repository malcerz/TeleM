"""
Analysis script for ETAP 8S Benchmark Results.
"""
import csv
import json
import statistics
from pathlib import Path

root = Path("c:/_DEV/TeleM")
audit_dir = root / "Raporty" / "etap8s_artifacts"
results_file = audit_dir / "etap8s_benchmark_results.json"

with open(results_file) as f:
    data = json.load(f)

print("=================================================================")
print("                   ETAP 8S BENCHMARK ANALYSIS                    ")
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
        "charts": q(charts),
        "gauge": q(gauges),
        "map": q(maps),
        "hud": q(huds),
    }

def analyze_runs(run_list, label):
    fpss, effs, rwalls, twalls, gpu_spans, vp_submits = [], [], [], [], [], []
    for r in run_list:
        prof = r["profile"]
        e8p = prof["etap8p_a"]
        t = prof["timings"]
        fpss.append(e8p["render_fps"])
        effs.append(e8p["effective_fps"])
        rwalls.append(e8p["video_render_wall_ms"] / 1000.0)
        twalls.append(e8p["total_from_export_start_ms"] / 1000.0)
        vp_submits.append(t["VideoProcessor CPU submit"]["median_ms"])
        
        csv_p = r.get("gpu_timeline_csv")
        gpu_d = parse_gpu_csv(csv_p) if csv_p else None
        gpu_spans.append(gpu_d["span"][0] if gpu_d else 0.0)
        print(f"  {r['run_name']}: Render FPS={fpss[-1]:.3f}, Effective FPS={effs[-1]:.3f}, Render Wall={rwalls[-1]:.3f}s, Total Wall={twalls[-1]:.3f}s, VP Submit={vp_submits[-1]:.3f}ms, GPU Span={gpu_spans[-1]:.3f}ms")
        
    return {
        "label": label,
        "render_fps": statistics.median(fpss),
        "eff_fps": statistics.median(effs),
        "render_wall": statistics.median(rwalls),
        "total_wall": statistics.median(twalls),
        "vp_submit": statistics.median(vp_submits),
        "gpu_span": statistics.median(gpu_spans),
    }

print("--- 1. 3 x BEFORE (1131 frames 4K, LEGACY 5-Flush) ---")
m_bef = analyze_runs(data["before_1131"], "BEFORE (5-Flush)")
print(f"  --> MEDIAN: Render FPS={m_bef['render_fps']:.3f}, Effective FPS={m_bef['eff_fps']:.3f}, VP Submit={m_bef['vp_submit']:.3f}ms, GPU Span={m_bef['gpu_span']:.3f}ms, Total Wall={m_bef['total_wall']:.3f}s\n")

print("--- 2. 3 x AFTER (1131 frames 4K, BATCHED 0 intermediate Flushes) ---")
m_aft = analyze_runs(data["after_1131"], "AFTER (BATCHED)")
print(f"  --> MEDIAN: Render FPS={m_aft['render_fps']:.3f}, Effective FPS={m_aft['eff_fps']:.3f}, VP Submit={m_aft['vp_submit']:.3f}ms, GPU Span={m_aft['gpu_span']:.3f}ms, Total Wall={m_aft['total_wall']:.3f}s\n")

fps_gain = m_aft["render_fps"] - m_bef["render_fps"]
fps_gain_pct = (fps_gain / m_bef["render_fps"]) * 100.0
span_drop = m_bef["gpu_span"] - m_aft["gpu_span"]
vp_drop = m_bef["vp_submit"] - m_aft["vp_submit"]

print("=== 1131-FRAME COMPARISON (BEFORE vs AFTER) ===")
print(f"  Render FPS:                 {m_bef['render_fps']:.3f} -> {m_aft['render_fps']:.3f} FPS (+{fps_gain:.3f} FPS / +{fps_gain_pct:.2f}%)")
print(f"  GPU Span:                   {m_bef['gpu_span']:.3f} ms -> {m_aft['gpu_span']:.3f} ms (Reduced by {span_drop:.3f} ms / -{span_drop/m_bef['gpu_span']*100.0:.1f}%)")
print(f"  VP CPU Submit Time:         {m_bef['vp_submit']:.3f} ms -> {m_aft['vp_submit']:.3f} ms (Reduced by {vp_drop:.3f} ms / -{vp_drop/m_bef['vp_submit']*100.0:.1f}%)")
print(f"  Total Wall Time:            {m_bef['total_wall']:.3f} s -> {m_aft['total_wall']:.3f} s (Saved {m_bef['total_wall'] - m_aft['total_wall']:.3f} s)")

# Profiler OFF Production Run
r_off = data["after_prof_off"]
prof_off = r_off["profile"]["etap8p_a"]
print(f"\n--- 3. PROFILER-OFF PRODUCTION RUN (1131 frames 4K) ---")
print(f"  Render FPS:                 {prof_off['render_fps']:.3f} FPS")
print(f"  Effective FPS:              {prof_off['effective_fps']:.3f} FPS")
print(f"  Total Wall Time:            {prof_off['total_from_export_start_ms']/1000.0:.3f} s")

# 1080p Control
r_1080 = data["after_1080p"]
prof_1080 = r_1080["profile"]["etap8p_a"]
gpu_1080 = parse_gpu_csv(r_1080.get("gpu_timeline_csv"))
print(f"\n--- 4. 1080p RESOLUTION CONTROL ---")
print(f"  1080p Render FPS:           {prof_1080['render_fps']:.3f} FPS")
print(f"  1080p GPU Span:             {gpu_1080['span'][0]:.3f} ms" if gpu_1080 else "N/A")

# Full Material (5395 frames)
r_5395 = data["full_5395"]
prof_5395 = r_5395["profile"]["etap8p_a"]
gpu_5395 = parse_gpu_csv(r_5395.get("gpu_timeline_csv"))
print(f"\n--- 5. FULL 5395-FRAME MATERIAL (GX030120.MP4 4K) ---")
print(f"  Render FPS:                 {prof_5395['render_fps']:.3f} FPS (was 30.7 in 8P-B, was 38.4 in 8Q)")
print(f"  Effective FPS:              {prof_5395['effective_fps']:.3f} FPS")
print(f"  Render Wall Time:           {prof_5395['video_render_wall_ms']/1000.0:.3f} s")
print(f"  Total Wall Time:            {prof_5395['total_from_export_start_ms']/1000.0:.3f} s (was 148.8s in 8Q, was 182.6s in 8P-B)")
if gpu_5395:
    print(f"  GPU Span:                   {gpu_5395['span'][0]:.3f} ms (p95={gpu_5395['span'][1]:.3f} ms)")
    print(f"  - VideoProcessorBlt:        {gpu_5395['vp'][0]:.3f} ms")
    print(f"  - Map Resize+Blend:         {gpu_5395['map'][0]:.3f} ms")
    print(f"  - Fused NV12 HUD CS:        {gpu_5395['hud'][0]:.3f} ms")
