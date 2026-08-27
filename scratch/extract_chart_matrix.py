import json
import glob

for name in ["test1_hr_only", "test2_cadence_only", "test3_hr_cadence",
             "test4_chart_before_map", "test5_map_before_chart",
             "test6_chart_elem_before_map", "test7_chart_elem_after_map",
             "test8_full_preset", "gpu_charts_working", "cpu_charts_reference"]:
    p = "Raporty/AMD_RENDER_PATH_AUDIT/%s.mp4.amd_profile.json" % name
    try:
        d = json.load(open(p, encoding="utf-8"))
    except Exception as e:
        print("%-24s ERR %s" % (name, e))
        continue
    fa = d.get("frame_accounting", {})
    j = d.get("etap5j", {})
    t = d.get("timings", {})
    def g(k):
        v = t.get(k)
        return round(v["median_ms"], 3) if isinstance(v, dict) else None
    print("%-24s cad_gpu=%-3s hr_gpu=%-3s chart_path=%-10s render_fps=%-7.2f compose_med=%-6.2f above_med=%-6.2f consumer_native_med=%-6.2f" % (
        name,
        fa.get("cadence_gpu"), fa.get("hr_gpu"),
        j.get("chart_path"),
        d.get("etap8p_a", {}).get("render_fps") or 0,
        g("compose_overlay") or 0, g("above_total") or 0,
        g("consumer_native_call") or 0))
