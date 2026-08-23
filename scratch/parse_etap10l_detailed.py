import json
import statistics
from pathlib import Path

root = Path(__file__).resolve().parents[1]
data_path = root / "scratch" / "etap10l_detailed_measurements.json"

with open(data_path, "r", encoding="utf-8") as f:
    data = json.load(f)

frame_records = data["frame_records"]
exporter_profile = data["exporter_profile"]

print(f"Total frame records: {len(frame_records)}")

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

warmup = frame_records[:10]
steady = frame_records[10:]

# 1. Warm-up vs Steady-State for below & above
print("\n" + "="*80)
print("1. WARM-UP (Frames 1-10) vs STEADY-STATE (Frames 11-120)")
print("="*80)

for scope in ["below_compose_ms", "above_compose_ms"]:
    w_vals = [f.get(scope, 0.0) for f in warmup]
    s_vals = [f.get(scope, 0.0) for f in steady]
    all_vals = [f.get(scope, 0.0) for f in frame_records]
    
    st_w = stats(w_vals)
    st_s = stats(s_vals)
    st_all = stats(all_vals)
    
    print(f"\n--- {scope} ---")
    print(f"  Warm-up (1-10):   mean={st_w['mean']:.3f} ms, med={st_w['median']:.3f} ms, p90={st_w['p90']:.3f} ms, p95={st_w['p95']:.3f} ms, min={st_w['min']:.3f} ms, max={st_w['max']:.3f} ms")
    print(f"  Steady (11-120):  mean={st_s['mean']:.3f} ms, med={st_s['median']:.3f} ms, p90={st_s['p90']:.3f} ms, p95={st_s['p95']:.3f} ms, min={st_s['min']:.3f} ms, max={st_s['max']:.3f} ms")
    print(f"  All (1-120):      mean={st_all['mean']:.3f} ms, med={st_all['median']:.3f} ms")

# 2. CPU_BELOW_MAP Widget Timings (Steady State)
print("\n" + "="*80)
print("2. CPU_BELOW_MAP WIDGET TIMINGS (Steady-State Frames 11-120)")
print("="*80)

below_widgets = [
    ("time_display", "time_display"),
    ("dist_visual", "dist_visual"),
    ("fit_battery_pct_text", "fit_battery_pct_text"),
    ("fit_solar_pct_text", "fit_solar_pct_text"),
]

below_sum_mean = 0.0
below_rows = []
for disp_name, key in below_widgets:
    r_vals = [f.get(f"widget.{key}.render_ms", 0.0) for f in steady]
    p_vals = [f.get(f"widget.{key}.paste_ms", 0.0) for f in steady]
    t_vals = [r + p for r, p in zip(r_vals, p_vals)]
    
    st_r = stats(r_vals)
    st_p = stats(p_vals)
    st_t = stats(t_vals)
    below_sum_mean += st_t["mean"]
    below_rows.append((disp_name, st_r["mean"], st_p["mean"], st_t["mean"], st_t["median"], st_t["p95"], key))
    print(f"  {disp_name:<22} | render: {st_r['mean']:6.3f} ms | paste: {st_p['mean']:6.3f} ms | total: {st_t['mean']:6.3f} ms (med={st_t['median']:.3f}, p95={st_t['p95']:.3f})")

below_compose_mean = stats([f.get("below_compose_ms", 0.0) for f in steady])["mean"]
below_residual = below_compose_mean - below_sum_mean
print(f"\n  SUM(Below Widgets): {below_sum_mean:.3f} ms")
print(f"  CPU_BELOW total mean: {below_compose_mean:.3f} ms")
print(f"  CPU_BELOW RESIDUAL:   {below_residual:.3f} ms")

# 3. CPU_ABOVE_MAP Widget Timings (Steady State)
print("\n" + "="*80)
print("3. CPU_ABOVE_MAP WIDGET TIMINGS (Steady-State Frames 11-120)")
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

above_sum_mean = 0.0
above_rows = []
for disp_name, key in above_widgets:
    r_vals = [f.get(f"widget.{key}.render_ms", 0.0) for f in steady]
    p_vals = [f.get(f"widget.{key}.paste_ms", 0.0) for f in steady]
    t_vals = [r + p for r, p in zip(r_vals, p_vals)]
    
    st_r = stats(r_vals)
    st_p = stats(p_vals)
    st_t = stats(t_vals)
    above_sum_mean += st_t["mean"]
    above_rows.append((disp_name, st_r["mean"], st_p["mean"], st_t["mean"], st_t["median"], st_t["p95"], key))
    print(f"  {disp_name:<20} | render: {st_r['mean']:6.3f} ms | paste: {st_p['mean']:6.3f} ms | total: {st_t['mean']:6.3f} ms (med={st_t['median']:.3f}, p95={st_t['p95']:.3f})")

above_compose_mean = stats([f.get("above_compose_ms", 0.0) for f in steady])["mean"]
above_residual = above_compose_mean - above_sum_mean
print(f"\n  SUM(Above Widgets): {above_sum_mean:.3f} ms")
print(f"  CPU_ABOVE compose mean: {above_compose_mean:.3f} ms")
print(f"  CPU_ABOVE RESIDUAL:     {above_residual:.3f} ms")

# 4. Exporter Timings from .amd_profile.json
print("\n" + "="*80)
print("4. EXPORTER STAGE TIMINGS (from amd_profile.json)")
print("="*80)
timings = exporter_profile.get("timings", {})
for k, v in timings.items():
    if v.get("count", 0) > 0:
        print(f"  {k:<35} | avg: {v.get('avg_ms', 0.0):7.3f} ms | med: {v.get('median_ms', 0.0):7.3f} ms | p95: {v.get('p95_ms', 0.0):7.3f} ms | p99: {v.get('p99_ms', 0.0):7.3f} ms")

# 5. Summary Wall Times & FPS
print("\n" + "="*80)
print("5. SUMMARY WALL TIMES & FPS")
print("="*80)
etap8p = exporter_profile.get("etap8p_a", {})
for k, v in etap8p.items():
    if k != "wall_milestones_ms":
        print(f"  {k}: {v}")

print(f"  true_fps: {exporter_profile.get('true_fps')}")
