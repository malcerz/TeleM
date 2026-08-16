"""ETAP 5P — print full accounting summaries + 5N explanation from runs JSON."""
import json

d = json.load(open(r"Raporty/AMD_ETAP5G/etap5p_runs.json", encoding="utf-8"))
for tag in ("B", "C", "D"):
    e = d["runs"][tag].get("accounting") or {}
    if not e.get("enabled"):
        continue
    print(f"=== {tag} ({d['runs'][tag]['telemetry'] if 'telemetry' in d['runs'][tag] else ''}) ===")
    ft = e["frame_total_ms"]; un = e["unaccounted_ms"]
    print(f"  frame_total med={ft['median']:.3f} p95={ft['p95']:.3f} p99={ft['p99']:.3f}")
    print(f"  measured_med={e['measured_sum_median_ms']:.3f} unaccounted_med={un['median']:.3f} "
          f"({un['pct_of_frame']:.2f}%) accounted={e['accounted_pct']:.2f}%")
    print(f"  GC: coll={e['gc']['collections']} per_frame={e['gc']['collections_per_frame']:.3f} "
          f"total_pause={e['gc']['total_pause_ms']:.1f}ms max_pause={e['gc']['max_pause_ms']:.2f}ms")
    top = sorted(e["stages"].items(), key=lambda kv: -kv[1]["median_ms"])
    for i, (name, s) in enumerate(top, 1):
        print(f"    {i:2d}. {name:16s} med={s['median_ms']:7.3f} p95={s['p95_ms']:7.3f} "
              f"avg={s['avg_ms']:7.3f}  {s['median_ms']/ft['median']*100:5.1f}%")
    print()

print("=== 5N EXPLANATION (process_frame pacing) ===")
for tag in ("B", "C", "D"):
    r = d["runs"][tag]
    e = r.get("accounting") or {}
    tel = e.get("stages", {}).get("telemetry", {}).get("median_ms")
    pf = e.get("stages", {}).get("process_frame", {}).get("median_ms")
    ft = e.get("frame_total_ms", {}).get("median")
    print(f"  {tag}: tel={tel:.2f}ms process_frame={pf:.2f}ms frame_total={ft:.2f}ms "
          f"FPS={r['true_fps']:.2f} wall={r['wall']:.2f}s")
