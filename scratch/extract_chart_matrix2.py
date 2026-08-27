import json

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
    k = d.get("etap5k", {})
    j = d.get("etap5j", {})
    print("%-24s static_uploads=%-3s static_bytes=%-9s dyn_uploads=%-4s dyn_bytes=%-8s active=%s" % (
        name, k.get("static_uploads"), k.get("static_bytes_total"),
        k.get("dynamic_uploads"), k.get("dynamic_bytes_total"),
        j.get("active_gpu_charts")))
