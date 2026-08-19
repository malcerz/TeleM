"""
Analyze ETAP 8T-B benchmark results and produce comprehensive statistics.
"""
import json
import statistics
from pathlib import Path

root = Path("c:/_DEV/TeleM")
summary_file = root / "Raporty" / "etap8t_b_artifacts" / "etap8t_b_benchmark_results.json"

with open(summary_file) as f:
    data = json.load(f)

print("=== ETAP 8T-B BENCHMARK ANALYSIS ===")

def analyze_runs(run_list, label):
    render_fps_list = []
    eff_fps_list = []
    render_wall_list = []
    total_wall_list = []
    prod_prep_medians = []
    prod_q_wait_medians = []
    cons_q_wait_medians = []
    cons_upload_medians = []
    cons_native_medians = []
    pipeline_total_medians = []
    
    for r in run_list:
        prof = r.get("profile", {})
        wall_timings = prof.get("etap8p_a", {})
        timings = prof.get("timings", {})
        
        r_fps = wall_timings.get("render_fps", 0.0)
        e_fps = wall_timings.get("effective_fps", 0.0)
        r_wall = wall_timings.get("video_render_wall_ms", 0.0) / 1000.0
        t_wall = r.get("total_wall_s", 0.0)
        
        render_fps_list.append(r_fps)
        eff_fps_list.append(e_fps)
        render_wall_list.append(r_wall)
        total_wall_list.append(t_wall)
        
        if "producer_prepare" in timings:
            prod_prep_medians.append(timings["producer_prepare"]["median_ms"])
        if "producer_queue_wait" in timings:
            prod_q_wait_medians.append(timings["producer_queue_wait"]["median_ms"])
        if "consumer_queue_wait" in timings:
            cons_q_wait_medians.append(timings["consumer_queue_wait"]["median_ms"])
        if "consumer_upload" in timings:
            cons_upload_medians.append(timings["consumer_upload"]["median_ms"])
        if "consumer_native_call" in timings:
            cons_native_medians.append(timings["consumer_native_call"]["median_ms"])
        if "pipeline_total" in timings:
            pipeline_total_medians.append(timings["pipeline_total"]["median_ms"])
            
    print(f"\n--- {label} (3 Runs) ---")
    print(f"Render FPS:    {[round(x, 3) for x in render_fps_list]} -> Median: {statistics.median(render_fps_list):.3f} FPS")
    print(f"Effective FPS: {[round(x, 3) for x in eff_fps_list]} -> Median: {statistics.median(eff_fps_list):.3f} FPS")
    print(f"Render Wall:   {[round(x, 3) for x in render_wall_list]} -> Median: {statistics.median(render_wall_list):.3f} s")
    print(f"Total Wall:    {[round(x, 3) for x in total_wall_list]} -> Median: {statistics.median(total_wall_list):.3f} s")
    if prod_prep_medians:
        print(f"Producer Prepare Median: {statistics.median(prod_prep_medians):.3f} ms")
    if prod_q_wait_medians:
        print(f"Producer Queue Wait Median: {statistics.median(prod_q_wait_medians):.3f} ms")
    if cons_q_wait_medians:
        print(f"Consumer Queue Wait Median: {statistics.median(cons_q_wait_medians):.3f} ms")
    if cons_upload_medians:
        print(f"Consumer Upload Median: {statistics.median(cons_upload_medians):.3f} ms")
    if cons_native_medians:
        print(f"Consumer Native Call Median: {statistics.median(cons_native_medians):.3f} ms")
    if pipeline_total_medians:
        print(f"Pipeline Total Median: {statistics.median(pipeline_total_medians):.3f} ms")

analyze_runs(data["sync_1131"], "1. SYNC BASELINE (1131f 4K)")
analyze_runs(data["async_1131"], "2. ASYNC PIPELINE (1131f 4K)")

# Single runs
for k, label in [("async_ts_on", "3. ASYNC TS PROFILER ON"), ("async_1080p", "4. ASYNC 1080p"), ("full_5395", "5. FULL 5395f 4K")]:
    r = data[k]
    prof = r.get("profile", {})
    wall_timings = prof.get("etap8p_a", {})
    timings = prof.get("timings", {})
    print(f"\n--- {label} ---")
    print(f"Render FPS:    {wall_timings.get('render_fps', 0.0):.3f} FPS")
    print(f"Effective FPS: {wall_timings.get('effective_fps', 0.0):.3f} FPS")
    print(f"Render Wall:   {wall_timings.get('video_render_wall_ms', 0.0)/1000.0:.3f} s")
    print(f"Total Wall:    {r.get('total_wall_s', 0.0):.3f} s")
    if "producer_prepare" in timings:
        print(f"Producer Prepare Median: {timings['producer_prepare']['median_ms']:.3f} ms")
    if "producer_queue_wait" in timings:
        print(f"Producer Queue Wait Median: {timings['producer_queue_wait']['median_ms']:.3f} ms")
    if "consumer_queue_wait" in timings:
        print(f"Consumer Queue Wait Median: {timings['consumer_queue_wait']['median_ms']:.3f} ms")
    if "consumer_upload" in timings:
        print(f"Consumer Upload Median: {timings['consumer_upload']['median_ms']:.3f} ms")
    if "consumer_native_call" in timings:
        print(f"Consumer Native Call Median: {timings['consumer_native_call']['median_ms']:.3f} ms")
    if "pipeline_total" in timings:
        print(f"Pipeline Total Median: {timings['pipeline_total']['median_ms']:.3f} ms")

# Inspect timeline trace of async_1131 run 1
prof_async1 = data["async_1131"][0]["profile"]
timeline = prof_async1.get("etap8t_b", {}).get("timeline_trace", [])
print(f"\n--- TIMELINE TRACE OF FIRST 10 FRAMES (ASYNC RUN 1) ---")
for t in timeline[:10]:
    print(f"Frame {t['frame_idx']:2d}: Prod [{t['prod_begin']:.4f} -> {t['prod_end']:.4f}] ({t['prod_ms']:.2f}ms) | Cons [{t['cons_begin']:.4f} -> {t['cons_end']:.4f}] ({t['cons_ms']:.2f}ms)")
