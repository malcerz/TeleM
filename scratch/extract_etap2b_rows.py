"""Extract ETAP 2B benchmark rows from profile JSON / log tables."""
import json
from pathlib import Path

KEYS = ("producer_prepare", "compose_overlay", "above_compose", "above_total",
        "gauge_tobytes", "gauge_upload", "gauge_capture", "gauge_diff",
        "gauge_bytes_per_frame", "gauge_upload_calls", "consumer_upload",
        "consumer_native_call", "pipeline_total")

prof = json.loads(Path(
    "scratch/etap2a_test/etap2a_cand_full.mp4.amd_profile.json"
).read_text(encoding="utf-8"))
print("== CAND 2A-path (current build, rects unset), 1131f ==")
t = prof["timings"]
for k in KEYS:
    s = t.get(k, {})
    print(f"{k:24s} avg={s.get('avg_ms', 0):9.3f} "
          f"med={s.get('median_ms', 0):9.3f} p95={s.get('p95_ms', 0):9.3f}")
e = prof["etap5l"]
print("counters:", {k: v for k, v in e.items() if "etap2b" in k},
      "MiB/frame:", round(e["gauge_upload_mib_per_frame"], 4))
