import json

with open("scratch/etap5a_detailed_results.json") as f:
    d = json.load(f)

print("=== STEADY STATE PHASES (AVG / MEDIAN / P95 / MIN / MAX) ===")
steady = d["steady_stats"]
tot_avg = steady["total_job"]["avg"]

for k, v in steady.items():
    pct = (v["avg"] / tot_avg) * 100
    print(f"  {k:20s}: avg={v['avg']:6.3f} ms ({pct:5.1f}%) | med={v['median']:6.3f} ms | p95={v['p95']:6.3f} ms | [{v['min']:.2f} - {v['max']:.2f}] ms")

print("\n=== PER-INDICATOR TOTALS & COMPOSE BREAKDOWN ===")
ind_b = d["indicators_breakdown"]
ind_totals = []
for k, v in ind_b.items():
    tot = v.get("total", {}).get("avg_ms", 0.0)
    rend = v.get("render", {}).get("avg_ms", 0.0)
    rot = v.get("rotate", {}).get("avg_ms", 0.0)
    paste = v.get("paste_composite", {}).get("avg_ms", 0.0)
    ind_totals.append((k, tot, rend, rot, paste))

ind_totals.sort(key=lambda x: x[1], reverse=True)
comp_tot_avg = sum(x[1] for x in ind_totals)

for k, tot, rend, rot, paste in ind_totals:
    pct = (tot / max(0.001, comp_tot_avg)) * 100
    print(f"  {k:30s} | total={tot:6.3f} ms ({pct:5.1f}%) | rend={rend:6.3f} ms | rot={rot:6.3f} ms | paste={paste:6.3f} ms")

print("\n=== PILLOW OPERATIONS ===")
pil = d["pillow_ops"]
pil_list = sorted(pil.items(), key=lambda x: x[1]["avg_ms"], reverse=True)
for k, v in pil_list:
    print(f"  {k:25s} | avg={v['avg_ms']:6.3f} ms | med={v['median_ms']:6.3f} ms | p95={v['p95_ms']:6.3f} ms | calls={v['avg_calls']:.1f}")

print("\n=== ROTATION MATRIX ===")
for k, v in d.get("rotation_stats", {}).items():
    print(f"  {k:25s} | total={v['total_ms']:6.3f} ms | render={v['render_ms']:6.3f} ms | paste={v['paste_ms']:6.3f} ms")

print("\n=== MULTIPROCESSING STATS ===")
mp = d.get("mp_stats", {})
print(f"  Elapsed: {mp.get('elapsed_s',0):.3f} s | FPS: {mp.get('fps',0):.1f} | avg wait: {mp.get('avg_wait_ms',0):.2f} ms | p95 wait: {mp.get('p95_wait_ms',0):.2f} ms | in-flight: {mp.get('avg_in_flight',0):.1f}")
