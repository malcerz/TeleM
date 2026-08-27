import csv

rows = list(csv.DictReader(open(r"Raporty/AMD_RENDER_PATH_AUDIT/account_4k_full_300f.mp4.frame_trace.csv", encoding="utf-8")))
print("=== Representative steady-state frame (idx 150) ===")
r = rows[150]
for k, v in r.items():
    print("  %-44s %s" % (k, v))
print("\n=== Spike frame (idx 30) ===")
r = rows[30]
for k, v in r.items():
    print("  %-44s %s" % (k, v))

# CPU vs GPU chart cost
print("\n=== GPU_SPLIT vs CPU_REFERENCE chart cost (1080p, HR+CAD) ===")
import json
for name in ("gpu_charts_working", "cpu_charts_reference"):
    d = json.load(open("Raporty/AMD_RENDER_PATH_AUDIT/%s.mp4.amd_profile.json" % name, encoding="utf-8"))
    t = d["timings"]
    print("  %s: render_fps=%.2f" % (name, d["etap8p_a"]["render_fps"]))
    for k in ("compose_overlay", "consumer_native_call", "VideoProcessor GPU completion",
              "GPU wait/synchronization", "pipeline_total", "producer_prepare"):
        v = t.get(k)
        if v:
            print("    %-38s med=%8.2f mean=%8.2f" % (k, v["median_ms"], v["avg_ms"]))
