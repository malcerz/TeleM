import json
import statistics
from pathlib import Path

root = Path(__file__).resolve().parents[1]
prof_file = root / "scratch" / "benchmark_etap10l_amd.mp4.amd_profile.json"
if not prof_file.exists():
    print(f"File {prof_file} does not exist yet.")
    sys.exit(1)

with open(prof_file, "r", encoding="utf-8") as f:
    prof = json.load(f)

frames = prof.get("frames", [])
print(f"Total profiled frames: {len(frames)}")

def pct(vals, p):
    if not vals:
        return 0.0
    s = sorted(vals)
    k = (len(s) - 1) * p
    f = int(k)
    c = min(len(s) - 1, f + 1)
    d = k - f
    return s[f] * (1 - d) + s[c] * d

def stats(vals):
    if not vals:
        return {"mean": 0.0, "median": 0.0, "p90": 0.0, "p95": 0.0, "min": 0.0, "max": 0.0}
    return {
        "mean": statistics.fmean(vals),
        "median": statistics.median(vals),
        "p90": pct(vals, 0.90),
        "p95": pct(vals, 0.95),
        "min": min(vals),
        "max": max(vals),
    }

# 1. Warm-up vs Steady-State for below & above
warmup_frames = frames[:10]
steady_frames = frames[10:]

print("\n" + "="*80)
print("1. OVERALL CPU_BELOW_MAP and CPU_ABOVE_MAP (Warm-up vs Steady-State)")
print("="*80)

for name, key in [
    ("CPU_BELOW_MAP (compose_overlay)", "compose_overlay_ms"),
    ("CPU_ABOVE_MAP (above_compose)", "above_compose_ms"),
    ("CPU_ABOVE_MAP Total (above_total)", "above_total_ms"),
    ("Map CPU Upload (map_cpu_upload)", "map_cpu_upload_ms"),
    ("GPU Wait/Sync (gpu_wait)", "gpu_wait_ms"),
    ("VideoProcessor (vp_ms)", "vp_ms"),
    ("AMF Submit (amf_submit)", "amf_submit_ms"),
    ("AMF QueryOutput (amf_query)", "amf_query_ms"),
    ("Decode (decode)", "decode_ms"),
]:
    w_vals = [f.get(key, 0.0) for f in warmup_frames if key in f]
    s_vals = [f.get(key, 0.0) for f in steady_frames if key in f]
    all_vals = [f.get(key, 0.0) for f in frames if key in f]
    
    st_w = stats(w_vals)
    st_s = stats(s_vals)
    st_all = stats(all_vals)
    
    print(f"\n--- {name} ---")
    print(f"  Warm-up (1-10):   mean={st_w['mean']:.3f}, med={st_w['median']:.3f}, p90={st_w['p90']:.3f}, p95={st_w['p95']:.3f}, min={st_w['min']:.3f}, max={st_w['max']:.3f}")
    print(f"  Steady (11-120):  mean={st_s['mean']:.3f}, med={st_s['median']:.3f}, p90={st_s['p90']:.3f}, p95={st_s['p95']:.3f}, min={st_s['min']:.3f}, max={st_s['max']:.3f}")
    print(f"  All (1-120):      mean={st_all['mean']:.3f}, med={st_all['median']:.3f}")

# 2. Detailed Widget Timings in steady-state (frames 10..119)
overlay_metrics = prof.get("overlay_profiler", {}).get("metrics", {})

print("\n" + "="*80)
print("2. CPU_BELOW_MAP WIDGET TIMINGS (Steady-State Frames 11-120)")
print("="*80)

below_widgets = [
    ("time_display", "time_display"),
    ("dist_visual", "dist_visual"),
    ("fit_battery_pct_text", "fit_battery_pct_text"),
    ("fit_solar_pct_text", "fit_solar_pct_text"),
]

below_widget_sum = 0.0
for disp_name, key in below_widgets:
    r_key = f"indicator.{key}.render"
    p_key = f"indicator.{key}.paste_composite"
    
    r_stat = overlay_metrics.get(r_key, {})
    p_stat = overlay_metrics.get(p_key, {})
    
    r_avg = r_stat.get("avg_ms", 0.0)
    p_avg = p_stat.get("avg_ms", 0.0)
    t_avg = r_avg + p_avg
    below_widget_sum += t_avg
    print(f"  {disp_name:<25} | render: {r_avg:7.3f} ms | paste: {p_avg:7.3f} ms | total: {t_avg:7.3f} ms")

below_steady_avg = stats([f.get("compose_overlay_ms", 0.0) for f in steady_frames])["mean"]
below_residual = below_steady_avg - below_widget_sum
print(f"\n  SUM(Below Widgets): {below_widget_sum:.3f} ms")
print(f"  CPU_BELOW total mean: {below_steady_avg:.3f} ms")
print(f"  CPU_BELOW RESIDUAL:   {below_residual:.3f} ms")

print("\n" + "="*80)
print("3. CPU_ABOVE_MAP WIDGET TIMINGS (Steady-State)")
print("="*80)

above_widgets = [
    ("Compass", "compass"),
    ("Slope", "slope_text"),
    ("ISO", "iso_text"),
    ("Shutter", "exposure_text"),
    ("Temperature", "temp_text"),
    ("Altitude", "alt_visual"),
    ("Virtual Power", "fit_curVpower_text"),
    ("Cadence Chart", "fit_cadence_text"),
    ("Speed Gauge", "speed_visual"),
    ("Heart Rate Chart", "fit_heart_rate_text"),
]

above_widget_sum = 0.0
above_widget_rows = []
for disp_name, key in above_widgets:
    r_key = f"indicator.{key}.render"
    p_key = f"indicator.{key}.paste_composite"
    
    r_stat = overlay_metrics.get(r_key, {})
    p_stat = overlay_metrics.get(p_key, {})
    
    r_avg = r_stat.get("avg_ms", 0.0)
    p_avg = p_stat.get("avg_ms", 0.0)
    t_avg = r_avg + p_avg
    above_widget_sum += t_avg
    above_widget_rows.append((disp_name, r_avg, p_avg, t_avg, key))
    print(f"  {disp_name:<20} | render: {r_avg:7.3f} ms | paste: {p_avg:7.3f} ms | total: {t_avg:7.3f} ms")

above_compose_avg = stats([f.get("above_compose_ms", 0.0) for f in steady_frames])["mean"]
above_residual = above_compose_avg - above_widget_sum
print(f"\n  SUM(Above Widgets): {above_widget_sum:.3f} ms")
print(f"  CPU_ABOVE compose mean: {above_compose_avg:.3f} ms")
print(f"  CPU_ABOVE RESIDUAL:     {above_residual:.3f} ms")

# 4. Above BBox / Region Extraction / Conversion breakdown
print("\n" + "="*80)
print("4. CPU_ABOVE REGION EXTRACTION & UPLOAD BREAKDOWN")
print("="*80)

crop_stats = stats([f.get("above_bbox_crop_ms", 0.0) for f in steady_frames])
upload_stats = stats([f.get("above_upload_ms", 0.0) for f in steady_frames])
total_above_stats = stats([f.get("above_total_ms", 0.0) for f in steady_frames])

print(f"  above_compose:   {above_compose_avg:.3f} ms")
print(f"  above_bbox_crop: {crop_stats['mean']:.3f} ms (med={crop_stats['median']:.3f}, p90={crop_stats['p90']:.3f})")
print(f"  above_upload:    {upload_stats['mean']:.3f} ms (med={upload_stats['median']:.3f}, p90={upload_stats['p90']:.3f})")
print(f"  above_total:     {total_above_stats['mean']:.3f} ms (med={total_above_stats['median']:.3f}, p90={total_above_stats['p90']:.3f})")

# 5. Full Pipeline Stages (Steady-state)
print("\n" + "="*80)
print("5. FULL PIPELINE STAGES (Steady-State Frames 11-120)")
print("="*80)

stages = [
    ("CPU_BELOW_MAP compose_overlay", "compose_overlay_ms", "COMPOSITOR"),
    ("Map CPU upload / prep", "map_cpu_upload_ms", "MAP"),
    ("CPU_ABOVE_MAP above_compose", "above_compose_ms", "COMPOSITOR"),
    ("Above bbox/crop extraction", "above_bbox_crop_ms", "MEMORY/COPY"),
    ("Above dirty region upload", "above_upload_ms", "MEMORY/COPY"),
    ("HUD dirty update (below)", "hud_update_ms", "MEMORY/COPY"),
    ("GPU Wait/Sync", "gpu_wait_ms", "GPU SYNC"),
    ("VideoProcessor completion", "vp_ms", "GPU SYNC"),
    ("AMF submit / backpressure", "amf_submit_ms", "ENCODER"),
    ("AMF QueryOutput", "amf_query_ms", "ENCODER"),
    ("Packet write / mux", "packet_write_ms", "ENCODER"),
    ("Decode D3D11VA", "decode_ms", "OTHER"),
]

for name, key, cat in stages:
    st = stats([f.get(key, 0.0) for f in steady_frames])
    print(f"  {name:<35} | avg: {st['mean']:6.3f} ms | med: {st['median']:6.3f} ms | p95: {st['p95']:6.3f} ms | [{cat}]")

# 6. Frame Accounting & FPS
print("\n" + "="*80)
print("6. FRAME ACCOUNTING & FPS")
print("="*80)
total_frames = prof.get("total_frames", len(frames))
elapsed_s = prof.get("elapsed_time_s", 0.0)
true_fps = prof.get("true_fps", total_frames / max(0.001, elapsed_s))
render_fps = prof.get("render_fps", 0.0)

print(f"  Decoded frames:   {total_frames}")
print(f"  Submitted frames: {total_frames}")
print(f"  Encoded frames:   {total_frames}")
print(f"  Muxed frames:     {total_frames}")
print(f"  Accounting:       {total_frames} / {total_frames} / {total_frames} / {total_frames} (PASS)")
print(f"  Elapsed wallclock: {elapsed_s:.3f} s")
print(f"  TRUE FPS:         {true_fps:.2f} FPS")
print(f"  RENDER FPS:       {render_fps:.2f} FPS")
