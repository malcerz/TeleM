import csv
import json
import statistics
from pathlib import Path

fa_csv = Path("scratch/etap3a_bench/baseline_gpu_lean_300f.mp4.frame_accounting.csv")
gpu_csv = Path("scratch/etap3a_bench/baseline_gpu_lean_300f.mp4.gpu_timeline.csv")
prof_json = Path("scratch/etap3a_bench/baseline_gpu_lean_300f.mp4.amd_profile.json")

print("=" * 100)
print("PHASE 2 & 3: COMPREHENSIVE NATIVE CONSUMER BREAKDOWN (300 FRAMES, 4K)")
print("=" * 100)

if prof_json.exists():
    p = json.load(open(prof_json))
    timings = p.get("timings", {})
    print("TOP-LEVEL TIMINGS (AVG / MEDIAN / P95):")
    for k in ["producer_prepare", "above_compose", "above_total", "consumer_upload", "consumer_native_call", "pipeline_total", "VideoProcessor GPU completion", "GPU wait/synchronization", "VideoProcessor CPU submit"]:
        if k in timings:
            t = timings[k]
            print(f"  {k:<32}: avg={t['avg_ms']:8.3f} ms, med={t['median_ms']:8.3f} ms, p95={t['p95_ms']:8.3f} ms")

if fa_csv.exists():
    rows = []
    with open(fa_csv, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for r in reader:
            rows.append({k: float(v) for k, v in r.items() if v != ""})

    print("\n" + "-" * 100)
    print("NATIVE PER-STAGE FRAME ACCOUNTING (CPU WALL MS):")
    print(f"{'Stage':<25} {'Mean (ms)':<12} {'Median (ms)':<12} {'P95 (ms)':<12} {'Max (ms)':<12} {'% of process_frame'}")
    print("-" * 100)

    total_proc = [r["process_frame_total"] for r in rows if "process_frame_total" in r]
    mean_proc = statistics.mean(total_proc) if total_proc else 1.0

    cols = [
        "surf_acquire", "vp_total", "vp_setup", "vp_blt", "vp_submit_window",
        "vp_range_pass", "clear_prev_above", "vp_chart_blend", "chart_flush",
        "vp_gauge_blend", "gauge_flush", "map_resample", "vp_map_blend",
        "map_flush1", "map_flush2", "above_blend", "above_flush", "flush_total",
        "vp_hud_compute", "vp_release_view", "amf_create_surface",
        "amf_submit_input", "amf_query", "amf_packet_write", "process_frame_total"
    ]
    for col in cols:
        vals = [r[col] for r in rows if col in r]
        if vals:
            m = statistics.mean(vals)
            med = statistics.median(vals)
            p95 = sorted(vals)[int(len(vals) * 0.95)]
            mx = max(vals)
            pct = (m / mean_proc) * 100.0
            print(f"{col:<25} {m:<12.3f} {med:<12.3f} {p95:<12.3f} {mx:<12.3f} {pct:6.2f}%")

if gpu_csv.exists():
    g_rows = []
    with open(gpu_csv, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for r in reader:
            g_rows.append({k: float(v) for k, v in r.items() if v != ""})

    print("\n" + "-" * 100)
    print("GPU HARDWARE TIMELINE (GPU EXECUTION SPAN MS):")
    print(f"{'Stage':<25} {'Mean (ms)':<12} {'Median (ms)':<12} {'P95 (ms)':<12} {'Max (ms)':<12}")
    print("-" * 100)
    gpu_cols = ["span_ms", "vp_ms", "range_ms", "charts_ms", "gauge_ms", "map_ms", "hud_ms"]
    for col in gpu_cols:
        vals = [r[col] for r in g_rows if col in r]
        if vals:
            m = statistics.mean(vals)
            med = statistics.median(vals)
            p95 = sorted(vals)[int(len(vals) * 0.95)]
            mx = max(vals)
            print(f"{col:<25} {m:<12.3f} {med:<12.3f} {p95:<12.3f} {mx:<12.3f}")
