import json

p = json.load(open(r"Raporty/AMD_RENDER_PATH_AUDIT/alloc_tracemalloc_720p.mp4.amd_profile.json", encoding="utf-8"))
print("=== AUDIT_ALLOCATIONS ===")
print(json.dumps(p.get("audit_allocations"), indent=1))
t = p["timings"]
for k in ("producer_alloc_blocks", "producer_alloc_traced_bytes", "consumer_alloc_blocks", "consumer_alloc_traced_bytes"):
    if k in t:
        print(k, json.dumps(t[k]))
print("=== ETAP5A overlay profile (per-widget) ===")
print(json.dumps(p.get("etap5a", {}), indent=1)[:3000])

print("\n--- tracemalloc top sites (from summary) ---")
d = json.load(open(r"Raporty/AMD_RENDER_PATH_AUDIT/audit_summary.json", encoding="utf-8"))
r = [x for x in d if x["name"] == "alloc_tracemalloc_720p"][0]
tm = r.get("tracemalloc")
if tm:
    print("current_bytes:", tm["current_bytes"], " peak_bytes:", tm["peak_bytes"])
    for s in tm["top_sites"][:25]:
        line = "  %-46s size=%12d count=%9d" % (s["file"], s["size"], s["count"])
        print(line)
else:
    print("no tracemalloc data")
