"""Generate full statistical tables for RAPORT_TELEM_ETAP_8F.md."""
import json
from pathlib import Path
import numpy as np

out_dir = Path("c:/_DEV/TeleM/Raporty/AMD_ETAP8F")

runs = [
    "8ffull1", "8ffull2", "8ffull3",
    "8f_ablation_full", "8f_ablation_map_off", "8f_ablation_gauge_off", "8f_ablation_map_gauge_off",
    "8f_control_hud_only", "8f_profile_off", "8f_profile_on"
]

def parse_csv(path: Path):
    if not path.exists():
        return {}
    lines = path.read_text(encoding="utf-8").strip().splitlines()
    if len(lines) < 2:
        return {}
    headers = [h.strip() for h in lines[0].split(",")]
    cols = {h: [] for h in headers}
    for line in lines[1:]:
        if not line.strip():
            continue
        parts = line.split(",")
        if len(parts) != len(headers):
            continue
        for h, p in zip(headers, parts):
            try:
                cols[h].append(float(p))
            except ValueError:
                cols[h].append(0.0)
    return {h: np.array(v) for h, v in cols.items()}

stats_all = {}
for r in runs:
    csv_native = out_dir / f"{r}.mp4.frame_accounting.csv"
    csv_gpu = out_dir / f"{r}.mp4.gpu_timeline.csv"
    data_nat = parse_csv(csv_native)
    data_gpu = parse_csv(csv_gpu)
    stats_all[r] = {"native": data_nat, "gpu": data_gpu}

print("=== 3x BASELINE RUN STATS ===")
for r in ("8ffull1", "8ffull2", "8ffull3"):
    nat = stats_all[r]["native"]
    gpu = stats_all[r]["gpu"]
    if "process_frame_total" in nat:
        pf = nat["process_frame_total"]
        vp = nat["vp_total"]
        flush = nat.get("flush_total", np.zeros_like(pf))
        amf_sub = nat["amf_submit_input"]
        amf_q = nat["amf_query"]
        amf_w = nat["amf_packet_write"]
        print(f"[{r}] PF total: med={np.median(pf):.3f}, p95={np.percentile(pf, 95):.3f}, mean={np.mean(pf):.3f} | VP total: med={np.median(vp):.3f}, p95={np.percentile(vp, 95):.3f} | Flush: med={np.median(flush):.3f}, p95={np.percentile(flush, 95):.3f} | AMF sub: med={np.median(amf_sub):.3f} | AMF q: med={np.median(amf_q):.3f} | AMF w: med={np.median(amf_w):.3f}")
    if "span_ms" in gpu:
        span = gpu["span_ms"]
        print(f"[{r} GPU] Span: med={np.median(span):.3f}, p95={np.percentile(span, 95):.3f}, mean={np.mean(span):.3f}")

print("\n=== ABLATION MATRIX STATS ===")
for r in ("8f_ablation_full", "8f_ablation_map_off", "8f_ablation_gauge_off", "8f_ablation_map_gauge_off"):
    nat = stats_all[r]["native"]
    gpu = stats_all[r]["gpu"]
    if "process_frame_total" in nat:
        pf = nat["process_frame_total"]
        vp = nat["vp_total"]
        flush = nat.get("flush_total", np.zeros_like(pf))
        print(f"[{r}] PF total: med={np.median(pf):.3f}, p95={np.percentile(pf, 95):.3f} | VP: med={np.median(vp):.3f}, p95={np.percentile(vp, 95):.3f} | Flush: med={np.median(flush):.3f}, p95={np.percentile(flush, 95):.3f}")
    if "span_ms" in gpu:
        span = gpu["span_ms"]
        print(f"[{r} GPU] Span: med={np.median(span):.3f}, p95={np.percentile(span, 95):.3f}")

print("\n=== DETAILED SUB-TIMERS (8ffull1) ===")
nat1 = stats_all["8ffull1"]["native"]
for k in ["surf_acquire", "vp_total", "vp_blt", "clear_prev_above", "vp_chart_blend", "chart_flush", "vp_gauge_blend", "gauge_flush", "map_resample", "map_flush1", "vp_map_blend", "map_flush2", "above_blend", "above_flush", "flush_total", "vp_hud_compute", "vp_release_view", "amf_create_surface", "amf_submit_input", "amf_query", "amf_packet_write", "process_frame_total"]:
    if k in nat1:
        v = nat1[k]
        print(f"{k:20s}: med={np.median(v):.3f} ms, p95={np.percentile(v, 95):.3f} ms, mean={np.mean(v):.3f} ms, max={np.max(v):.3f} ms")

print("\n=== DETAILED GPU TIMERS (8ffull1) ===")
gpu1 = stats_all["8ffull1"]["gpu"]
for k in ["span_ms", "vp_ms", "range_ms", "charts_ms", "gauge_ms", "map_ms", "hud_ms"]:
    if k in gpu1:
        v = gpu1[k]
        print(f"{k:20s}: med={np.median(v):.3f} ms, p95={np.percentile(v, 95):.3f} ms, mean={np.mean(v):.3f} ms, max={np.max(v):.3f} ms")
