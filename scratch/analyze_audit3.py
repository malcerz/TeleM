"""AMD Audit 3 — analysis and partial report generation.

Reads all available profiles and generates structured data for the report.
Can be run while benchmarks are still running — it processes whatever is available.
"""

from __future__ import annotations
import csv
import json
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AUDIT_DIR = ROOT / "Raporty" / "AMD_RENDER_PATH_AUDIT"
AUDIT2_DIR = ROOT / "Raporty" / "AMD_RENDER_PATH_AUDIT_2"
OUT3 = ROOT / "Raporty" / "AMD_RENDER_PATH_AUDIT_3"
OUT3.mkdir(parents=True, exist_ok=True)
PRESET_PATH = ROOT / "presets" / "cycling_dashboard_v10.json"

def pct(vals, p):
    if not vals:
        return 0.0
    s = sorted(vals)
    idx = (len(s) - 1) * p
    lo = int(idx)
    hi = min(len(s) - 1, lo + 1)
    return s[lo] + (s[hi] - s[lo]) * (idx - lo)

def stats(vals, warmup=30):
    v = vals[warmup:] if len(vals) > warmup else vals
    if not v:
        return {"n": 0, "mean": 0, "median": 0, "p95": 0, "p99": 0}
    return {
        "n": len(v),
        "mean": round(statistics.fmean(v), 3),
        "median": round(statistics.median(v), 3),
        "p95": round(pct(v, 0.95), 3),
        "p99": round(pct(v, 0.99), 3),
    }

def load_profile(path):
    if not path.exists():
        return None
    with open(path) as f:
        return json.load(f)

def extract_timing(profile, key):
    if not profile:
        return {}
    t = profile.get("timings", {}).get(key, {})
    return {
        "avg": round(t.get("avg_ms", 0), 3),
        "med": round(t.get("median_ms", 0), 3),
        "p95": round(t.get("p95_ms", 0), 3),
        "p99": round(t.get("p99_ms", 0), 3),
    }

def extract_render_fps(profile):
    if not profile:
        return None
    return round(profile.get("etap8p_a", {}).get("render_fps", 0), 2)

def extract_true_fps(profile):
    if not profile:
        return None
    return round(profile.get("true_fps", 0), 2)

def read_frame_trace_csv(csv_path):
    if not csv_path.exists():
        return []
    rows = []
    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            out = {}
            for k, v in row.items():
                try:
                    out[k] = float(v)
                except (ValueError, TypeError):
                    out[k] = v
            rows.append(out)
    return rows

def classify_stalls(frame_rows, warmup=30):
    """Classify stall events by severity from frame_trace CSV."""
    rows = frame_rows[warmup:]
    # Try to find frame_total_ms column
    total_col = None
    for col in ["frame_total_ms", "pipeline_total_ms", "consumer_native_ms"]:
        if rows and col in rows[0]:
            total_col = col
            break
    if not total_col:
        return {"error": "no frame total column found", "columns": list(rows[0].keys()) if rows else []}

    vals = [r[total_col] for r in rows if isinstance(r.get(total_col), float)]
    if not vals:
        return {"error": f"no float values in {total_col}"}

    thresholds = [100, 250, 500, 1000]
    result = {"total_frames": len(vals), "column": total_col}
    for t in thresholds:
        stalls = [v for v in vals if v > t]
        result[f"stalls_gt_{t}ms"] = {
            "count": len(stalls),
            "pct": round(100.0 * len(stalls) / max(1, len(vals)), 2),
            "max": round(max(stalls), 1) if stalls else 0,
            "mean_when_stall": round(statistics.fmean(stalls), 1) if stalls else 0,
        }
    return result

# ── LOAD ALL AVAILABLE PROFILES ─────────────────────────────────────────
PROFILES = {
    # From Audit 1 (Run A+B)
    "A_1080p_full":    load_profile(AUDIT_DIR / "test_A_1080p_full.mp4.amd_profile.json"),
    "B_4k_full":       load_profile(AUDIT_DIR / "test_B_4k_full.mp4.amd_profile.json"),
    "C_1080p_nohud":   load_profile(AUDIT_DIR / "test_C_1080p_nohud.mp4.amd_profile.json"),
    "D_4k_nohud":      load_profile(AUDIT_DIR / "test_D_4k_nohud.mp4.amd_profile.json"),
    # From Audit 2 (300f)
    "acct_4k_300f":    load_profile(AUDIT_DIR / "account_4k_full_300f.mp4.amd_profile.json"),
    "acct_4knohud":    load_profile(AUDIT_DIR / "account_4k_nohud_300f.mp4.amd_profile.json"),
    # From Audit 3 (new runs)
    "a3_1080p":        load_profile(AUDIT_DIR / "audit3_above_1080p.mp4.amd_profile.json"),
    "a3_4k":           load_profile(AUDIT_DIR / "audit3_above_4k.mp4.amd_profile.json"),
    "a3_cpu_1080p":    load_profile(AUDIT_DIR / "audit3_cpu_ref_1080p.mp4.amd_profile.json"),
    "a3_gpu_1080p":    load_profile(AUDIT_DIR / "audit3_gpu_split_1080p.mp4.amd_profile.json"),
    "a3_cpu_4k":       load_profile(AUDIT_DIR / "audit3_cpu_ref_4k.mp4.amd_profile.json"),
    "a3_gpu_4k":       load_profile(AUDIT_DIR / "audit3_gpu_split_4k.mp4.amd_profile.json"),
    "a3_soak":         load_profile(AUDIT_DIR / "audit3_soak_4k_nohud.mp4.amd_profile.json"),
    "a3_trace":        load_profile(AUDIT_DIR / "audit3_chart_trace_full.mp4.amd_profile.json"),
    "a3_gpu_split_hrcad": load_profile(AUDIT_DIR / "audit3_gpu_split_hr_cad.mp4.amd_profile.json"),
}

# ── FRAME TRACE CSVs ─────────────────────────────────────────────────────
FT = {
    "a3_1080p":     read_frame_trace_csv(AUDIT_DIR / "audit3_above_1080p.mp4.frame_trace.csv"),
    "a3_4k":        read_frame_trace_csv(AUDIT_DIR / "audit3_above_4k.mp4.frame_trace.csv"),
    "a3_soak":      read_frame_trace_csv(AUDIT_DIR / "audit3_soak_4k_nohud.mp4.frame_trace.csv"),
    "a3_cpu_1080p": read_frame_trace_csv(AUDIT_DIR / "audit3_cpu_ref_1080p.mp4.frame_trace.csv"),
    "a3_gpu_1080p": read_frame_trace_csv(AUDIT_DIR / "audit3_gpu_split_1080p.mp4.frame_trace.csv"),
    "a3_cpu_4k":    read_frame_trace_csv(AUDIT_DIR / "audit3_cpu_ref_4k.mp4.frame_trace.csv"),
    "a3_gpu_4k":    read_frame_trace_csv(AUDIT_DIR / "audit3_gpu_split_4k.mp4.frame_trace.csv"),
}

print("=== Profiles loaded ===")
for name, p in PROFILES.items():
    status = "OK" if p else "MISSING"
    fps = extract_render_fps(p) if p else "?"
    print(f"  {name:25s}: {status}  render_fps={fps}")

# ── PART 1+2: ABOVE-MAP COST BREAKDOWN ─────────────────────────────────
print("\n=== PART 1+2: ABOVE-MAP COST BREAKDOWN ===")
ABOVE_TIMING_KEYS = [
    "above_compose",
    "above_region_to_bytes",
    "above_region_upload",
    "above_tight_bbox_collect",
    "above_exact_union",
    "above_exact_crop",
    "above_bbox_tracking",
    "above_total",
    "compose_overlay",
    "map_cpu_upload",
    "producer_prepare",
    "consumer_native_call",
    "VideoProcessor GPU completion",
    "GPU wait/synchronization",
    "consumer_upload",
]

above_table = {}
for res_label, p_key in [("1080p (audit3)", "a3_1080p"), ("4K (audit2-300f)", "acct_4k_300f")]:
    p = PROFILES[p_key]
    if not p:
        print(f"  {res_label}: MISSING")
        continue
    row = {}
    for k in ABOVE_TIMING_KEYS:
        t = extract_timing(p, k)
        row[k] = t
    above_table[res_label] = row
    print(f"\n  {res_label} (render_fps={extract_render_fps(p)}):")
    print(f"    {'Key':<35} {'avg':>8} {'med':>8} {'p95':>8} {'p99':>8}")
    for k, t in row.items():
        print(f"    {k:<35} {t.get('avg',0):>8.3f} {t.get('med',0):>8.3f} {t.get('p95',0):>8.3f} {t.get('p99',0):>8.3f}")

(OUT3 / "above_timing_breakdown.json").write_text(
    json.dumps(above_table, indent=2), encoding="utf-8"
)

# ── PART 3+4: DIRTY REGION PIPELINE ANALYSIS ────────────────────────────
print("\n=== PART 3+4: DIRTY REGION PIPELINE ===")
DIRTY_KEYS = [
    "above_bbox_tracking",
    "above_exact_union",
    "above_exact_crop",
    "above_tight_bbox_collect",
    "above_region_to_bytes",
    "above_region_upload",
    "above_upload_buffer_prepare",
]
for res_label, p_key in [("1080p", "a3_1080p"), ("4K (audit2)", "acct_4k_300f")]:
    p = PROFILES[p_key]
    if not p:
        continue
    print(f"\n  {res_label}:")
    etap8n = p.get("etap8n", {})
    print(f"    regions/frame: {etap8n.get('regions_per_frame', {})}")
    print(f"    bytes/frame: {etap8n.get('uploaded_bytes_per_frame', {})}")
    print(f"    pixels/frame: {etap8n.get('uploaded_pixels_per_frame', {})}")
    for k in DIRTY_KEYS:
        t = extract_timing(p, k)
        print(f"    {k:<35} avg={t.get('avg',0):.3f}ms  med={t.get('med',0):.3f}ms  p95={t.get('p95',0):.3f}ms")

# ── PART 9: CPU_REFERENCE vs GPU_SPLIT ──────────────────────────────────
print("\n=== PART 9: CPU_REFERENCE vs GPU_SPLIT ===")
compare_table = {}
for res, pairs in [
    ("1080p", [("CPU_REFERENCE", "a3_cpu_1080p"), ("GPU_SPLIT", "a3_gpu_1080p")]),
    ("4K",    [("CPU_REFERENCE", "a3_cpu_4k"),    ("GPU_SPLIT", "a3_gpu_4k")]),
]:
    print(f"\n  {res}:")
    print(f"    {'Mode':<16} {'render_fps':>10} {'above_compose avg':>18} {'compose_overlay avg':>20} {'producer_prepare avg':>21}")
    for mode, pkey in pairs:
        p = PROFILES[pkey]
        if not p:
            print(f"    {mode:<16} MISSING")
            continue
        rfps = extract_render_fps(p)
        ac = extract_timing(p, "above_compose").get("avg", 0)
        co = extract_timing(p, "compose_overlay").get("avg", 0)
        pp = extract_timing(p, "producer_prepare").get("avg", 0)
        print(f"    {mode:<16} {rfps:>10.2f} {ac:>18.3f} {co:>20.3f} {pp:>21.3f}")
        compare_table.setdefault(res, {})[mode] = {
            "render_fps": rfps,
            "above_compose_avg_ms": ac,
            "compose_overlay_avg_ms": co,
            "producer_prepare_avg_ms": pp,
        }
(OUT3 / "compare_cpu_gpu_split.json").write_text(
    json.dumps(compare_table, indent=2), encoding="utf-8"
)

# ── PART 10+11: STALL ANALYSIS ──────────────────────────────────────────
print("\n=== PART 10+11: STALL ANALYSIS ===")
for label, ft_rows in FT.items():
    if not ft_rows:
        print(f"  {label}: no frame trace data")
        continue
    # Print column names first
    if ft_rows:
        print(f"  {label}: {len(ft_rows)} rows, cols: {list(ft_rows[0].keys())[:10]}")
    sc = classify_stalls(ft_rows, warmup=30)
    print(f"  {label}: {sc}")

# Check if we have frame_accounting CSV instead
for label, csv_name in [
    ("a3_1080p", "audit3_above_1080p.mp4.frame_accounting.csv"),
    ("a3_4k",    "audit3_above_4k.mp4.frame_accounting.csv"),
    ("a3_soak",  "audit3_soak_4k_nohud.mp4.frame_accounting.csv"),
]:
    fa_path = AUDIT_DIR / csv_name
    if not fa_path.exists():
        continue
    rows = []
    with open(fa_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append({k: float(v) if v.replace('.','',1).replace('-','',1).isdigit() else v
                         for k, v in row.items()})
    if rows:
        print(f"  [FA CSV] {label}: {len(rows)} rows, cols: {list(rows[0].keys())[:15]}")

# ── PART 14: GPU BUSY-WAIT (from native frame accounting) ───────────────
print("\n=== PART 14: GPU BUSY-WAIT ===")
for label, p_key in [("1080p", "a3_1080p"), ("4K (acct)", "acct_4k_300f")]:
    p = PROFILES[p_key]
    if not p:
        continue
    t_vp_cpu = extract_timing(p, "VideoProcessor CPU submit")
    t_vp_gpu = extract_timing(p, "VideoProcessor GPU completion")
    t_gpu_wait = extract_timing(p, "GPU wait/synchronization")
    print(f"  {label}:")
    print(f"    VP CPU submit:    avg={t_vp_cpu['avg']:.3f}ms  med={t_vp_cpu['med']:.3f}ms  p95={t_vp_cpu['p95']:.3f}ms")
    print(f"    VP GPU complete:  avg={t_vp_gpu['avg']:.3f}ms  med={t_vp_gpu['med']:.3f}ms  p95={t_vp_gpu['p95']:.3f}ms")
    print(f"    GPU wait (busy):  avg={t_gpu_wait['avg']:.3f}ms  med={t_gpu_wait['med']:.3f}ms  p95={t_gpu_wait['p95']:.3f}ms")
    print(f"    Note: GPU wait IS busy-wait (GetData loop in telem_amd_native.cpp)")

# ── LOAD PRESET FOR STATIC ANALYSIS ─────────────────────────────────────
print("\n=== PART 5: Z-ORDER (from preset) ===")
with open(PRESET_PATH) as f:
    layout = json.load(f)
before_map = True
zorder = {"BELOW_MAP": [], "MAP": [], "ABOVE_MAP": []}
for key, cfg in layout.get("indicators", {}).items():
    if key == "time_display":
        zorder["BELOW_MAP"].insert(0, f"{key} [{cfg.get('form','?')}] (always-first)")
        continue
    if key == "track_map":
        zorder["MAP"].append(f"{key} [{cfg.get('form','?')}]")
        before_map = False
        continue
    bucket = "BELOW_MAP" if before_map else "ABOVE_MAP"
    zorder[bucket].append(f"{key} [{cfg.get('form','?')}]")

for bucket, items in zorder.items():
    print(f"  {bucket}: {items}")

(OUT3 / "zorder_table.json").write_text(json.dumps(zorder, indent=2), encoding="utf-8")

print("\nAnalysis complete. Data saved to", OUT3)
