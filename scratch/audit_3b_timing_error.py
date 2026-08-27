import json
from pathlib import Path

raw_3b = json.load(open("Raporty/AMD_ETAP_3B/etap3b_audit_raw.json"))
final_3b = json.load(open("Raporty/AMD_ETAP_3B/etap3b_final_ab_results.json"))

print("=" * 90)
print("AUDITING TIMINGS IN 3B PROFILES")
print("=" * 90)

for name, p in [("REF_2001f (audit_raw)", raw_3b["long_baseline_2001f"]),
                ("CAND_2001f (final_ab)", final_3b["cand_2001f"])]:
    wall = p.get("total_wall_clock_s", 0)
    fa = p.get("frame_accounting", {})
    t = p.get("timings", {})
    mux = t.get("Audio mux", {}).get("avg_ms", 0) / 1000.0
    print(f"\n{name}:")
    print(f"  total_wall_clock_s: {wall:.3f} s")
    print(f"  audio_mux_s:        {mux:.3f} s")
    print(f"  wall - mux:         {wall - mux:.3f} s")
    print(f"  frames encoded:     {fa.get('amf_output', 0)}")
    print(f"  frames requested:   {fa.get('requested_frames', 0)}")
    print(f"  TRUE FPS:           {p.get('true_fps', 0):.3f}")
