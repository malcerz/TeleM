import json
from pathlib import Path

res_p = Path("Raporty/AMD_ETAP_3B/etap3b_final_ab_results.json")
data = json.load(open(res_p, encoding="utf-8"))

def extract_row(prof):
    timings = prof.get("timings", {})
    t_fps = prof.get("true_fps", 0)
    r_fps = prof.get("etap8pa_summary", {}).get("render_fps", 0)
    u_fps = prof.get("etap8pa_summary", {}).get("user_effective_fps", 0)
    v_wall = prof.get("etap8pa_summary", {}).get("video_render_wall_ms", 0) / 1000.0
    ac_avg = timings.get("above_compose", {}).get("avg_ms", 0)
    ac_p95 = timings.get("above_compose", {}).get("p95_ms", 0)
    at_avg = timings.get("above_total", {}).get("avg_ms", 0)
    pp_avg = timings.get("producer_prepare", {}).get("avg_ms", 0)
    pp_p95 = timings.get("producer_prepare", {}).get("p95_ms", 0)
    cn_avg = timings.get("consumer_native_call", {}).get("avg_ms", 0)
    pt_avg = timings.get("pipeline_total", {}).get("avg_ms", 0)
    return {
        "v_wall": v_wall, "r_fps": r_fps, "u_fps": u_fps, "t_fps": t_fps,
        "pp_avg": pp_avg, "pp_p95": pp_p95,
        "ac_avg": ac_avg, "ac_p95": ac_p95,
        "at_avg": at_avg, "cn_avg": cn_avg, "pt_avg": pt_avg
    }

print("=" * 100)
print("FINAL A/B RESULTS SUMMARY (ETAP 3B)")
print("=" * 100)

ref_300 = extract_row(data["ref_300f"])
cand_300 = extract_row(data["cand_300f"])
ref_2001 = extract_row(data["ref_2001f"])
cand_2001 = extract_row(data["cand_2001f"])

print("\n1. SHORT PIPELINE A/B (300 FRAMES, def_layout.json, 4K):")
print(f"{'Metric':<25} {'REF':<15} {'CAND':<15} {'Delta'}")
print("-" * 75)
for k in ["r_fps", "pp_avg", "pp_p95", "ac_avg", "ac_p95", "at_avg", "cn_avg", "pt_avg"]:
    r = ref_300[k]
    c = cand_300[k]
    d = c - r
    print(f"{k:<25} {r:<15.3f} {c:<15.3f} {d:+10.3f}")

print("\n2. LONG PIPELINE A/B (2001 FRAMES, def_layout.json, 4K):")
print(f"{'Metric':<25} {'REF':<15} {'CAND':<15} {'Delta'}")
print("-" * 75)
for k in ["v_wall", "r_fps", "t_fps", "pp_avg", "pp_p95", "ac_avg", "ac_p95", "at_avg", "cn_avg", "pt_avg"]:
    r = ref_2001[k]
    c = cand_2001[k]
    d = c - r
    print(f"{k:<25} {r:<15.3f} {c:<15.3f} {d:+10.3f}")
