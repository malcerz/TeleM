"""ETAP 5O — print full AMF diagnostics from runs JSON."""
import json

d = json.load(open(r"Raporty/AMD_ETAP5G/etap5o_runs.json", encoding="utf-8"))
for k in ("A", "B", "C", "D", "E"):
    r = d["runs"][k]
    q = r.get("queue"); c = r.get("cadence")
    print(f'{k} {r["mode"]:13s} FPS={r["true_fps"]:.2f} wall={r["wall"]:.2f}')
    if q:
        print(f'    queue avg={q["avg"]:.2f} med={q["median"]} p95={q["p95"]} '
              f'p99={q["p99"]} max={q["max"]} trend={q["trend"]}')
    if c:
        print(f'    cadence med={c["median_interval_ms"]:.1f}ms '
              f'p95={c["p95_interval_ms"]:.1f}ms equivFPS={c["equivalent_fps"]:.1f}')
    print(f'    final_outstanding={r["outstanding_at_final_submit"]} '
          f'drain={r["drain_ms"]:.0f}ms({r["frames_drained_in_flush"]}) '
          f'input_full={r["input_full_total"]} sub={r["submitted"]} out={r["output"]}')
print()
print("aggregate:", json.dumps(d.get("aggregate", {}), indent=1))
