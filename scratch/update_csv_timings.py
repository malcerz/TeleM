import csv
import json
from pathlib import Path

csv_p = Path("Raporty/AMD_ETAP_3C/benchmark_runs.csv")

rows = []

# 1. REF Baseline (Long 2001f from 3B)
raw_3b = json.load(open("Raporty/AMD_ETAP_3B/etap3b_audit_raw.json"))
ref_prof = raw_3b["long_baseline_2001f"]
ref_t = ref_prof["timings"]
ref_total_wall = ref_prof.get("total_wall_clock_s", 83.187)
ref_mux = ref_t.get("Audio mux", {}).get("avg_ms", 3181.0) / 1000.0
ref_render_wall = ref_total_wall - ref_mux
rows.append({
    "run_id": "ref_baseline_2001f",
    "variant": "REF_BAR_TEXT",
    "frames": 2001,
    "video_render_wall_s": round(ref_render_wall, 3),
    "calculated_fps": round(2001.0 / ref_render_wall, 3),
    "producer_avg_ms": round(ref_t["producer_prepare"]["avg_ms"], 3),
    "above_avg_ms": round(ref_t["above_compose"]["avg_ms"], 3),
    "above_total_ms": round(ref_t["above_total"]["avg_ms"], 3),
    "consumer_avg_ms": round(ref_t["consumer_native_call"]["avg_ms"], 3),
})

# 2. CAND 3B (Bar Opt 2001f)
final_3b = json.load(open("Raporty/AMD_ETAP_3B/etap3b_final_ab_results.json"))
cand3b_prof = final_3b["cand_2001f"]
cand3b_t = cand3b_prof["timings"]
cand3b_total_wall = cand3b_prof.get("total_wall_clock_s", 86.650)
cand3b_mux = cand3b_t.get("Audio mux", {}).get("avg_ms", 3134.0) / 1000.0
cand3b_render_wall = cand3b_total_wall - cand3b_mux
rows.append({
    "run_id": "cand_bar_2001f",
    "variant": "CAND_BAR_ONLY",
    "frames": 2001,
    "video_render_wall_s": round(cand3b_render_wall, 3),
    "calculated_fps": round(2001.0 / cand3b_render_wall, 3),
    "producer_avg_ms": round(cand3b_t["producer_prepare"]["avg_ms"], 3),
    "above_avg_ms": round(cand3b_t["above_compose"]["avg_ms"], 3),
    "above_total_ms": round(cand3b_t["above_total"]["avg_ms"], 3),
    "consumer_avg_ms": round(cand3b_t["consumer_native_call"]["avg_ms"], 3),
})

# 3. CAND 3C Short 600f
p600 = json.load(open("scratch/etap3c_bench/cand_text_600f_600f.mp4.amd_profile.json"))
t600 = p600["timings"]
w600_total = p600.get("total_wall_clock_s", 30.0)
m600 = t600.get("Audio mux", {}).get("avg_ms", 0) / 1000.0
w600_render = w600_total - m600
rows.append({
    "run_id": "cand_text_600f",
    "variant": "CAND_TEXT_AND_BAR",
    "frames": 600,
    "video_render_wall_s": round(w600_render, 3),
    "calculated_fps": round(600.0 / w600_render, 3),
    "producer_avg_ms": round(t600["producer_prepare"]["avg_ms"], 3),
    "above_avg_ms": round(t600["above_compose"]["avg_ms"], 3),
    "above_total_ms": round(t600["above_total"]["avg_ms"], 3),
    "consumer_avg_ms": round(t600["consumer_native_call"]["avg_ms"], 3),
})

# 4. CAND 3C Long 2001f
p2001 = json.load(open("scratch/etap3c_bench/cand_text_2001f_2001f.mp4.amd_profile.json"))
t2001 = p2001["timings"]
w2001_total = p2001.get("total_wall_clock_s", 91.512)
m2001 = t2001.get("Audio mux", {}).get("avg_ms", 4228.0) / 1000.0
w2001_render = w2001_total - m2001
rows.append({
    "run_id": "cand_text_2001f",
    "variant": "CAND_TEXT_AND_BAR",
    "frames": 2001,
    "video_render_wall_s": round(w2001_render, 3),
    "calculated_fps": round(2001.0 / w2001_render, 3),
    "producer_avg_ms": round(t2001["producer_prepare"]["avg_ms"], 3),
    "above_avg_ms": round(t2001["above_compose"]["avg_ms"], 3),
    "above_total_ms": round(t2001["above_total"]["avg_ms"], 3),
    "consumer_avg_ms": round(t2001["consumer_native_call"]["avg_ms"], 3),
})

with open(csv_p, "w", newline="", encoding="utf-8") as f:
    writer = csv.DictWriter(f, fieldnames=[
        "run_id", "variant", "frames", "video_render_wall_s", "calculated_fps",
        "producer_avg_ms", "above_avg_ms", "above_total_ms", "consumer_avg_ms"
    ])
    writer.writeheader()
    writer.writerows(rows)

print("Updated benchmark_runs.csv successfully:")
for r in rows:
    print(r)
