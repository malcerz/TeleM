import json
from pathlib import Path

raw_p = Path("Raporty/AMD_ETAP_3B/etap3b_audit_raw.json")
data = json.load(open(raw_p, encoding="utf-8"))

print("=" * 110)
print("AMD ETAP 3B: AUDIT RESULTS - LONG BASELINE & ABLATION MATRIX")
print("=" * 110)

def extract_summary(prof):
    timings = prof.get("timings", {})
    t_fps = prof.get("true_fps", 0)
    wall = prof.get("total_wall_clock_s", 0)
    ac = timings.get("above_compose", {}).get("avg_ms", 0)
    ac_med = timings.get("above_compose", {}).get("median_ms", 0)
    ac_p95 = timings.get("above_compose", {}).get("p95_ms", 0)
    at = timings.get("above_total", {}).get("avg_ms", 0)
    pp = timings.get("producer_prepare", {}).get("avg_ms", 0)
    pp_med = timings.get("producer_prepare", {}).get("median_ms", 0)
    pp_p95 = timings.get("producer_prepare", {}).get("p95_ms", 0)
    cn = timings.get("consumer_native_call", {}).get("avg_ms", 0)
    pt = timings.get("pipeline_total", {}).get("avg_ms", 0)
    audio_mux = timings.get("Audio mux", {}).get("avg_ms", 0)
    cnt = prof.get("measured_total_frames", 300)
    
    # RENDER FPS excludes audio mux
    render_wall_s = max(0.001, wall - (audio_mux / 1000.0))
    r_fps = cnt / render_wall_s if render_wall_s > 0 else t_fps

    return {
        "cnt": cnt, "r_fps": r_fps, "t_fps": t_fps, "wall": wall,
        "ac": ac, "ac_med": ac_med, "ac_p95": ac_p95,
        "at": at, "pp": pp, "pp_med": pp_med, "pp_p95": pp_p95,
        "cn": cn, "pt": pt, "audio_mux": audio_mux
    }

print("\n1. LONG BASELINE (2001 FRAMES GX030120 / def_layout.json / 4K):")
print("-" * 110)
s_long = extract_summary(data["long_baseline_2001f"])
print(f"  Total Wall Clock:         {s_long['wall']:8.3f} s")
print(f"  TRUE FPS:                 {s_long['t_fps']:8.3f} fps")
print(f"  RENDER FPS:               {s_long['r_fps']:8.3f} fps")
print(f"  above_compose (avg/med/p95): {s_long['ac']:8.3f} ms / {s_long['ac_med']:8.3f} ms / {s_long['ac_p95']:8.3f} ms")
print(f"  above_total (avg):        {s_long['at']:8.3f} ms")
print(f"  producer_prepare (avg/med/p95): {s_long['pp']:8.3f} ms / {s_long['pp_med']:8.3f} ms / {s_long['pp_p95']:8.3f} ms")
print(f"  consumer_native_call:     {s_long['cn']:8.3f} ms")
print(f"  pipeline_total:           {s_long['pt']:8.3f} ms")

print("\n2. ABLATION MATRIX (300 FRAMES PER RUN, def_layout.json / 4K):")
print("-" * 110)
s_base = extract_summary(data["abl_full_300f"])
print(f"{'Run / Target Disabled':<28} {'RENDER FPS':<12} {'dFPS':<10} {'above_comp (ms)':<16} {'dAbove (ms)':<14} {'prod_prep (ms)':<15} {'dProd (ms)'}")
print(f"{'BASELINE FULL (ALL ON)':<28} {s_base['r_fps']:<12.3f} {'0.000':<10} {s_base['ac']:<16.3f} {'0.000':<14} {s_base['pp']:<15.3f} {'0.000'}")

ablation_keys = [k for k in data.keys() if k.startswith("abl_off_")]
for k in ablation_keys:
    s = extract_summary(data[k])
    d_fps = s['r_fps'] - s_base['r_fps']
    d_ac = s['ac'] - s_base['ac']
    d_pp = s['pp'] - s_base['pp']
    target_name = k.replace("abl_off_", "")
    print(f"{target_name:<28} {s['r_fps']:<12.3f} {d_fps:+10.3f} {s['ac']:<16.3f} {d_ac:+14.3f} {s['pp']:<15.3f} {d_pp:+10.3f}")
