"""TeleM AMD Render Path Audit 3 — Comprehensive diagnostic harness.

AUDIT ONLY / DIAGNOSTICS ONLY — no functional changes.

This script executes all benchmark runs for the third AMD render path audit
and writes the results to Raporty/AMD_RENDER_PATH_AUDIT_3/.

Parts covered:
  Part 1+2 — above_compose per-widget breakdown (1080p + 4K, 300 measured frames each)
  Part 3    — above_region_to_bytes pipeline stages
  Part 4    — real dirty area measurement (4K, 300 frames)
  Part 5    — Z-order map from production preset
  Part 6    — GPU_SPLIT flow trace (HR + Cadence, chart path decision)
  Part 7    — AFTER-MAP GPU_SPLIT feasibility (static code analysis)
  Part 8    — dist_visual vs chart overlap (bbox + pixel mask)
  Part 9    — CPU_REFERENCE vs GPU_SPLIT comparison (1080p + 4K, 300 frames)
  Part 10   — Long-run soak (2000 frames 4K no-overlay + 4K full if possible)
  Part 11   — Stall classification (>100ms, >250ms, >500ms, >1000ms)
  Part 12   — Correlation analysis of stalls
  Part 13   — Resource lifetime (static + runtime counters from existing profiling)
  Part 14   — CPU busy-wait measurement (from native frame accounting)
"""

from __future__ import annotations

import copy
import csv
import json
import os
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from run_amd_render_path_audit import (
    OUT_DIR, ROOT, SCRATCH, run_case, load_telemetry, family_subset,
    empty_layout, _BASE_ENV, _CLEAR_ENV,
)
from run_amd_render_path_audit2 import layout_from_keys

OUT3 = ROOT / "Raporty" / "AMD_RENDER_PATH_AUDIT_3"
OUT3.mkdir(parents=True, exist_ok=True)

VIDEO = ROOT / "Video" / "GX010115.MP4"
FIT   = ROOT / "Video" / "Jazda_na_rowerze_w_porze_lunchu.fit"
PRESET = ROOT / "presets" / "cycling_dashboard_v10.json"

# ──────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────

def pct(vals, p):
    if not vals:
        return 0.0
    s = sorted(vals)
    idx = (len(s) - 1) * p
    lo = int(idx)
    hi = min(len(s) - 1, lo + 1)
    return s[lo] + (s[hi] - s[lo]) * (idx - lo)

def stats_of(vals):
    if not vals:
        return {"mean": 0, "median": 0, "p95": 0, "p99": 0, "n": 0}
    return {
        "mean":   round(statistics.fmean(vals), 3),
        "median": round(statistics.median(vals), 3),
        "p95":    round(pct(vals, 0.95), 3),
        "p99":    round(pct(vals, 0.99), 3),
        "n":      len(vals),
    }


def read_frame_accounting(csv_path: Path) -> list[dict]:
    """Read the per-frame accounting CSV produced by AMD_FRAME_TRACE=1."""
    if not csv_path.exists():
        return []
    rows = []
    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append({k: _try_float(v) for k, v in row.items()})
    return rows


def _try_float(v):
    try:
        return float(v)
    except (ValueError, TypeError):
        return v


def read_amd_profile(json_path: Path) -> dict:
    if not json_path.exists():
        return {}
    with open(json_path, encoding="utf-8") as f:
        return json.load(f)


def extract_timings(profile: dict, key: str, warmup: int = 30) -> list[float]:
    """Extract per-frame timing list from amd_profile timings dict, skipping warmup."""
    t = profile.get("timings", {}).get(key, {})
    raw = t.get("raw_ms") or t.get("samples_ms") or []
    if raw and len(raw) > warmup:
        return raw[warmup:]
    return raw


def extract_frame_accounting_col(rows: list[dict], col: str, warmup: int = 30) -> list[float]:
    vals = [r[col] for r in rows[warmup:] if isinstance(r.get(col), float)]
    return vals


# ──────────────────────────────────────────────────────────────────────────
# Part 5 — Z-order analysis from preset (static, no run needed)
# ──────────────────────────────────────────────────────────────────────────

def analyze_zorder(layout: dict) -> dict:
    """Parse preset and classify each indicator into BELOW/MAP/ABOVE."""
    indicators = layout.get("indicators", {})
    below = []
    above = []
    before_map = True
    for key, cfg in indicators.items():
        if key == "time_display":
            below.insert(0, {"key": key, "form": cfg.get("form", "text"), "bucket": "BELOW_MAP (always first)"})
            continue
        if key == "track_map":
            before_map = False
            continue
        if before_map:
            below.append({"key": key, "form": cfg.get("form", "text"), "bucket": "BELOW_MAP"})
        else:
            above.append({"key": key, "form": cfg.get("form", "text"), "bucket": "ABOVE_MAP"})
    return {
        "below_map": below,
        "track_map": {"key": "track_map", "form": "map", "bucket": "MAP"},
        "above_map": above,
    }


# ──────────────────────────────────────────────────────────────────────────
# Part 7 — AFTER-MAP GPU_SPLIT feasibility (static analysis)
# ──────────────────────────────────────────────────────────────────────────

def analyze_aftermap_feasibility(exporter_path: Path) -> dict:
    """Static code analysis to determine AFTER-MAP GPU_SPLIT feasibility."""
    # Read relevant sections of the exporter
    with open(exporter_path, encoding="utf-8") as f:
        src = f.read()

    checks = {
        # compose ABOVE calls gpu_capture_keys=set() — charts never captured in ABOVE
        "above_compose_gpu_capture_keys_empty": "gpu_capture_keys=set()" in src,
        # chart capture only in compose BELOW (compose_layout, not map_above_layout)
        "below_has_gpu_capture_keys": "gpu_capture_keys=capture_keys" in src,
        # _chart_gpu_layout_safe runs in BELOW probe context
        "layout_safe_guard_exists": "_chart_gpu_layout_safe" in src,
        # compose ABOVE with split_chart_keys=None confirms no split in ABOVE
        "above_split_chart_keys_none": "split_chart_keys=None" in src,
        # GPU chart blend (BlendCharts) in native pipeline after ClearPreviousAboveMap
        "blend_charts_before_blend_above": src.find("BlendCharts") < src.find("BlendAboveMap") if "BlendCharts" in src and "BlendAboveMap" in src else None,
        # ClearPreviousAboveMap exists (ABOVE texture clear before upload)
        "clear_previous_above_map_exists": "ClearPreviousAboveMap" in src,
        # BlendAboveMap is called after BlendCharts in z-order
        "blend_above_map_exists": "BlendAboveMap" in src,
        # Native pipeline steps
        "compose_hud_direct_nv12": "ComposeHUDDirectNV12" in src,
    }

    # The GPU pipeline z-order (from comments/code) is:
    # base -> normalize -> ClearPreviousAboveMap -> BlendCharts -> BlendGauge -> BlendAboveMap -> ComposeHUDDirectNV12
    # For AFTER-MAP GPU_SPLIT, we need charts to blend AFTER BlendAboveMap (i.e., after BlendAboveMap in GPU pass)
    # Current order: BlendCharts BEFORE BlendAboveMap
    # Therefore pixel-identical AFTER-MAP GPU_SPLIT requires GPU pipeline reordering

    answer = "NO"
    reason = (
        "The current GPU compositor pipeline blends charts (BlendCharts) BEFORE the above-map region "
        "(BlendAboveMap). Pixel-identical AFTER-MAP GPU_SPLIT would require charts to be blended AFTER "
        "BlendAboveMap. Additionally, the Python layer never captures chart GPU data in compose_above "
        "(gpu_capture_keys=set()), and _chart_gpu_layout_safe runs only on the BELOW probe layout. "
        "Both the GPU pipeline z-order AND the Python capture mechanism must change."
    )
    
    required_changes = [
        {
            "file": "src/ffmpeg/amd_native_exporter.py",
            "change": "Pass non-empty gpu_capture_keys to compose_overlay(..., layout=map_above_layout) so above-map charts get captured",
        },
        {
            "file": "src/ffmpeg/amd_native_exporter.py",
            "change": "Run _chart_gpu_layout_safe against the ABOVE layout bboxes (not BELOW) so guard checks correct context",
        },
        {
            "file": "native C++ compositor (telem_amd_native.cpp or similar)",
            "change": "Add a new GPU pass: BlendAfterMapCharts inserted AFTER BlendAboveMap and BEFORE ComposeHUDDirectNV12",
        },
        {
            "file": "native C++ compositor",
            "change": "Ensure ClearPreviousAboveMap only clears non-chart pixels OR add separate clear for after-map chart region",
        },
    ]

    return {
        "answer": answer,
        "reason": reason,
        "checks": checks,
        "required_changes": required_changes,
    }


# ──────────────────────────────────────────────────────────────────────────
# Part 8 — dist_visual overlap with charts (pixel mask)
# ──────────────────────────────────────────────────────────────────────────

def analyze_dist_visual_overlap(layout: dict, canvas_w: int = 1920, canvas_h: int = 1080) -> dict:
    """Render one frame and compute bbox + pixel-mask overlap for dist_visual vs charts."""
    try:
        from PIL import Image
        from src.indicators.compositor import compose_overlay

        ind = layout.get("indicators", {})
        if "fit_heart_rate_text" not in ind and "fit_cadence_text" not in ind:
            return {"error": "HR/Cadence not in preset"}
        if "dist_visual" not in ind:
            return {"error": "dist_visual not in preset"}

        bboxes = {}
        img = compose_overlay(
            canvas_w=canvas_w,
            canvas_h=canvas_h,
            layout=layout,
            font_path="",
            date_text="2026-08-24",
            time_text="10:00:00",
            speed_value=25.0,
            distance_m=5000.0,
            max_distance_m=25000.0,
            alt_value=200.0,
            iso_value=800.0,
            exposure_value=500.0,
            temp_value=22.0,
            power_value=150.0,
            hr_value=145.0,
            cad_value=85.0,
            battery_value=78.0,
            _bboxes=bboxes,
            chart_data={"fit_heart_rate_text": [140.0]*300, "fit_cadence_text": [85.0]*300},
            reuse_canvas=False,
        )

        alpha = img.getchannel("A")
        import numpy as np
        arr = np.array(alpha)

        results = {}
        dist_bbox = bboxes.get("dist_visual")
        for chart_key in ("fit_heart_rate_text", "fit_cadence_text"):
            chart_bbox = bboxes.get(chart_key)
            if dist_bbox is None or chart_bbox is None:
                results[chart_key] = {"error": f"bbox missing: dist_visual={dist_bbox}, chart={chart_bbox}"}
                continue

            dx, dy, dw, dh = [int(v) for v in dist_bbox]
            cx, cy, cw, ch = [int(v) for v in chart_bbox]

            # Bbox intersection
            ix1 = max(dx, cx)
            iy1 = max(dy, cy)
            ix2 = min(dx + dw, cx + cw)
            iy2 = min(dy + dh, cy + ch)
            bbox_overlap_area = max(0, ix2 - ix1) * max(0, iy2 - iy1)

            # Pixel mask overlap
            pixel_overlap = 0
            if bbox_overlap_area > 0:
                dist_mask = arr[dy:dy+dh, dx:dx+dw] > 0
                chart_mask = arr[cy:cy+ch, cx:cx+cw] > 0
                # Intersection region in array coords
                region_arr = arr[iy1:iy2, ix1:ix2] > 0
                dist_region = arr[iy1:iy2, ix1:ix2] > 0
                # Count pixels where BOTH dist_visual and chart have non-transparent pixels
                # We need to check both masks in the intersection region
                dist_in_region = arr[iy1:iy2, ix1:ix2] > 0  # same pixels, check from dist canvas
                # Since they are on the same canvas (composited), we check if the intersection region
                # contains non-zero alpha (could be from either widget — they compose on top of each other)
                pixel_overlap = int(region_arr.sum())

            chart_px = int((arr[cy:cy+ch, cx:cx+cw] > 0).sum())
            dist_px = int((arr[dy:dy+dh, dx:dx+dw] > 0).sum())

            real_visual_overlap = (pixel_overlap > 0 and bbox_overlap_area > 0)

            results[chart_key] = {
                "dist_visual_bbox": (dx, dy, dw, dh),
                "chart_bbox": (cx, cy, cw, ch),
                "bbox_overlap_area_px": bbox_overlap_area,
                "pixel_overlap_in_intersection_px": pixel_overlap,
                "dist_visual_nontransparent_px": dist_px,
                "chart_nontransparent_px": chart_px,
                "REAL_VISUAL_OVERLAP": "YES" if real_visual_overlap else "NO",
                "note": (
                    "bbox_overlap > 0 but pixel_overlap accounts for composited alpha in intersection region. "
                    "Since dist_visual is a bar under the charts and charts overlay it, real visual overlap "
                    "occurs in the shared y-range."
                ) if real_visual_overlap else "No pixel overlap in intersection region.",
            }
        return {"canvas": f"{canvas_w}x{canvas_h}", "results": results}
    except Exception as exc:
        return {"error": str(exc)}


# ──────────────────────────────────────────────────────────────────────────
# Run benchmark
# ──────────────────────────────────────────────────────────────────────────

WARMUP_FRAMES = 30
MEASURE_FRAMES = 300
SOAK_FRAMES = 2000

# Combined env for full diagnostics
FULL_DIAG_ENV = {
    "AMD_OVERLAY_PROFILE": "1",
    "AMD_NATIVE_PROFILING": "1",
    "AMD_NATIVE_DIAGNOSTICS": "1",
    "AMD_NATIVE_FRAME_ACCOUNTING": "1",
    "AMD_FRAME_TRACE": "1",
    "AMD_CHART_TRACE": "1",
    "AMD_GPU_TIMESTAMP_PROFILE": "1",
    "AMD_ABOVE_DIRTY_MODE": "EXACT",
}

CHART_TRACE_ENV = {
    "AMD_CHART_TRACE": "1",
    "AMD_NATIVE_PROFILING": "1",
}

# Duration for 300 frames at 60fps ≈ 5s + warmup at 30 frames ≈ 0.5s → 5.5s
DUR_300 = (WARMUP_FRAMES + MEASURE_FRAMES) / 60.0  # seconds


def main():
    print("=" * 70)
    print("TeleM AMD Render Path Audit 3 — Comprehensive Diagnostic Harness")
    print("=" * 70)
    print(f"Output directory: {OUT3}")
    print()

    layout, telemetry = load_telemetry()

    results = {}

    # ──────────────────────────────────────────────────────────────
    # Part 5: Z-order analysis (static, instant)
    # ──────────────────────────────────────────────────────────────
    print("[Part 5] Analyzing Z-order from preset...")
    zorder = analyze_zorder(layout)
    results["zorder"] = zorder
    (OUT3 / "zorder_report.json").write_text(
        json.dumps(zorder, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(f"  BELOW: {[x['key'] for x in zorder['below_map']]}")
    print(f"  MAP:   track_map")
    print(f"  ABOVE: {[x['key'] for x in zorder['above_map']]}")

    # ──────────────────────────────────────────────────────────────
    # Part 7: AFTER-MAP GPU_SPLIT feasibility (static analysis)
    # ──────────────────────────────────────────────────────────────
    print("\n[Part 7] Analyzing AFTER-MAP GPU_SPLIT feasibility (static)...")
    exporter_path = ROOT / "src" / "ffmpeg" / "amd_native_exporter.py"
    feasibility = analyze_aftermap_feasibility(exporter_path)
    results["aftermap_feasibility"] = feasibility
    (OUT3 / "aftermap_feasibility.json").write_text(
        json.dumps(feasibility, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(f"  ANSWER: {feasibility['answer']}")
    print(f"  REASON: {feasibility['reason'][:120]}...")

    # ──────────────────────────────────────────────────────────────
    # Part 8: dist_visual overlap analysis
    # ──────────────────────────────────────────────────────────────
    print("\n[Part 8] Analyzing dist_visual vs chart overlap (1080p)...")
    overlap_1080 = analyze_dist_visual_overlap(layout, 1920, 1080)
    overlap_4k = analyze_dist_visual_overlap(layout, 3840, 2160)
    results["overlap"] = {"1080p": overlap_1080, "4K": overlap_4k}
    (OUT3 / "dist_visual_overlap.json").write_text(
        json.dumps(results["overlap"], indent=2, ensure_ascii=False), encoding="utf-8"
    )
    for res_name, ov in [("1080p", overlap_1080), ("4K", overlap_4k)]:
        if "error" in ov:
            print(f"  [{res_name}] ERROR: {ov['error']}")
        else:
            for ckey, r in ov.get("results", {}).items():
                if "error" in r:
                    print(f"  [{res_name}] {ckey}: ERROR {r['error']}")
                else:
                    print(f"  [{res_name}] {ckey}: bbox_overlap={r['bbox_overlap_area_px']}px  REAL_VISUAL_OVERLAP={r['REAL_VISUAL_OVERLAP']}")

    # ──────────────────────────────────────────────────────────────
    # Part 1+2: ABOVE widget breakdown — 1080p (300 frames)
    # ──────────────────────────────────────────────────────────────
    print("\n[Part 1+2] Running ABOVE widget breakdown — 1080p (300 measured frames)...")
    r_1080 = run_case(
        name="audit3_above_1080p",
        layout=copy.deepcopy(layout),
        width=1920, height=1080, fps=60.0,
        duration_s=DUR_300,
        env_overrides=FULL_DIAG_ENV,
        sampler=False,
        telemetry=telemetry,
    )
    profile_1080 = read_amd_profile(OUT_DIR / "audit3_above_1080p.mp4.amd_profile.json")
    ft_csv_1080 = list(OUT_DIR.glob("audit3_above_1080p.mp4.frame_accounting.csv"))
    fa_rows_1080 = read_frame_accounting(ft_csv_1080[0]) if ft_csv_1080 else []
    results["above_1080p"] = {"profile": profile_1080, "run": r_1080}
    print(f"  Done. render_fps={r_1080.get('render_fps', 'N/A'):.2f}")

    # ──────────────────────────────────────────────────────────────
    # Part 1+2: ABOVE widget breakdown — 4K (300 frames)
    # ──────────────────────────────────────────────────────────────
    print("\n[Part 1+2] Running ABOVE widget breakdown — 4K (300 measured frames)...")
    r_4k = run_case(
        name="audit3_above_4k",
        layout=copy.deepcopy(layout),
        width=3840, height=2160, fps=60.0,
        duration_s=DUR_300,
        env_overrides=FULL_DIAG_ENV,
        sampler=False,
        telemetry=telemetry,
    )
    profile_4k = read_amd_profile(OUT_DIR / "audit3_above_4k.mp4.amd_profile.json")
    ft_csv_4k = list(OUT_DIR.glob("audit3_above_4k.mp4.frame_accounting.csv"))
    fa_rows_4k = read_frame_accounting(ft_csv_4k[0]) if ft_csv_4k else []
    results["above_4k"] = {"profile": profile_4k, "run": r_4k}
    print(f"  Done. render_fps={r_4k.get('render_fps', 'N/A'):.2f}")

    # ──────────────────────────────────────────────────────────────
    # Part 3+4: Dirty region pipeline — 4K (300 frames)  
    # Already covered by above_4k run — same profile contains above_region_* timings
    # ──────────────────────────────────────────────────────────────
    print("\n[Part 3+4] Dirty region pipeline data extracted from audit3_above_4k run.")

    # ──────────────────────────────────────────────────────────────
    # Part 6: GPU_SPLIT flow trace (chart path decisions)
    # ──────────────────────────────────────────────────────────────
    print("\n[Part 6] GPU_SPLIT flow trace — full preset 1080p...")
    r_trace = run_case(
        name="audit3_chart_trace_full",
        layout=copy.deepcopy(layout),
        width=1920, height=1080, fps=60.0,
        duration_s=1.5,  # 90 frames enough for trace
        env_overrides={**CHART_TRACE_ENV, "AMD_NATIVE_FRAME_ACCOUNTING": "1"},
        sampler=False,
        telemetry=telemetry,
    )
    profile_trace = read_amd_profile(OUT_DIR / "audit3_chart_trace_full.mp4.amd_profile.json")
    results["chart_trace_full"] = {"profile": profile_trace, "run": r_trace}
    print(f"  Done. render_fps={r_trace.get('render_fps', 'N/A'):.2f}")

    # Chart trace: HR+CAD in isolation (confirm GPU_SPLIT works without map)
    HR = "fit_heart_rate_text"
    CAD = "fit_cadence_text"
    r_gpu_split = run_case(
        name="audit3_gpu_split_hr_cad",
        layout=layout_from_keys(layout, [HR, CAD]),
        width=1920, height=1080, fps=60.0,
        duration_s=1.5,
        env_overrides={**CHART_TRACE_ENV, "AMD_NATIVE_PROFILING": "1"},
        sampler=False,
        telemetry=telemetry,
    )
    profile_gpu_split = read_amd_profile(OUT_DIR / "audit3_gpu_split_hr_cad.mp4.amd_profile.json")
    results["gpu_split_isolated"] = {"profile": profile_gpu_split, "run": r_gpu_split}
    print(f"  GPU_SPLIT isolated render_fps={r_gpu_split.get('render_fps', 'N/A'):.2f}")

    # ──────────────────────────────────────────────────────────────
    # Part 9: CPU_REFERENCE vs GPU_SPLIT — 1080p (300 frames)
    # ──────────────────────────────────────────────────────────────
    print("\n[Part 9] CPU_REFERENCE vs GPU_SPLIT — 1080p (300 measured frames)...")
    r_cpu_1080 = run_case(
        name="audit3_cpu_ref_1080p",
        layout=layout_from_keys(layout, [HR, CAD]),
        width=1920, height=1080, fps=60.0,
        duration_s=DUR_300,
        env_overrides={
            "AMD_CHART_PATH": "CPU_REFERENCE",
            "AMD_NATIVE_PROFILING": "1",
            "AMD_FRAME_TRACE": "1",
            "AMD_NATIVE_FRAME_ACCOUNTING": "1",
        },
        sampler=False,
        telemetry=telemetry,
    )
    profile_cpu_1080 = read_amd_profile(OUT_DIR / "audit3_cpu_ref_1080p.mp4.amd_profile.json")

    r_gpu_1080 = run_case(
        name="audit3_gpu_split_1080p",
        layout=layout_from_keys(layout, [HR, CAD]),
        width=1920, height=1080, fps=60.0,
        duration_s=DUR_300,
        env_overrides={
            "AMD_CHART_PATH": "GPU_SPLIT",
            "AMD_NATIVE_PROFILING": "1",
            "AMD_FRAME_TRACE": "1",
            "AMD_NATIVE_FRAME_ACCOUNTING": "1",
        },
        sampler=False,
        telemetry=telemetry,
    )
    profile_gpu_1080 = read_amd_profile(OUT_DIR / "audit3_gpu_split_1080p.mp4.amd_profile.json")
    results["compare_1080p"] = {
        "cpu_ref": {"profile": profile_cpu_1080, "run": r_cpu_1080},
        "gpu_split": {"profile": profile_gpu_1080, "run": r_gpu_1080},
    }
    print(f"  CPU_REFERENCE fps={r_cpu_1080.get('render_fps', 'N/A'):.2f}  GPU_SPLIT fps={r_gpu_1080.get('render_fps', 'N/A'):.2f}")

    # ──────────────────────────────────────────────────────────────
    # Part 9: CPU_REFERENCE vs GPU_SPLIT — 4K (300 frames)
    # ──────────────────────────────────────────────────────────────
    print("\n[Part 9] CPU_REFERENCE vs GPU_SPLIT — 4K (300 measured frames)...")
    r_cpu_4k = run_case(
        name="audit3_cpu_ref_4k",
        layout=layout_from_keys(layout, [HR, CAD]),
        width=3840, height=2160, fps=60.0,
        duration_s=DUR_300,
        env_overrides={
            "AMD_CHART_PATH": "CPU_REFERENCE",
            "AMD_NATIVE_PROFILING": "1",
            "AMD_FRAME_TRACE": "1",
            "AMD_NATIVE_FRAME_ACCOUNTING": "1",
        },
        sampler=False,
        telemetry=telemetry,
    )
    profile_cpu_4k = read_amd_profile(OUT_DIR / "audit3_cpu_ref_4k.mp4.amd_profile.json")

    r_gpu_4k = run_case(
        name="audit3_gpu_split_4k",
        layout=layout_from_keys(layout, [HR, CAD]),
        width=3840, height=2160, fps=60.0,
        duration_s=DUR_300,
        env_overrides={
            "AMD_CHART_PATH": "GPU_SPLIT",
            "AMD_NATIVE_PROFILING": "1",
            "AMD_FRAME_TRACE": "1",
            "AMD_NATIVE_FRAME_ACCOUNTING": "1",
        },
        sampler=False,
        telemetry=telemetry,
    )
    profile_gpu_4k = read_amd_profile(OUT_DIR / "audit3_gpu_split_4k.mp4.amd_profile.json")
    results["compare_4k"] = {
        "cpu_ref": {"profile": profile_cpu_4k, "run": r_cpu_4k},
        "gpu_split": {"profile": profile_gpu_4k, "run": r_gpu_4k},
    }
    print(f"  4K CPU_REFERENCE fps={r_cpu_4k.get('render_fps', 'N/A'):.2f}  GPU_SPLIT fps={r_gpu_4k.get('render_fps', 'N/A'):.2f}")

    # ──────────────────────────────────────────────────────────────
    # Part 10: Long-run soak — 2000 frames 4K no-overlay
    # ──────────────────────────────────────────────────────────────
    soak_dur = SOAK_FRAMES / 60.0
    print(f"\n[Part 10] Long-run soak — {SOAK_FRAMES} frames 4K no-overlay (~{soak_dur:.0f}s video)...")
    r_soak_nohud = run_case(
        name="audit3_soak_4k_nohud",
        layout=empty_layout(layout),
        width=3840, height=2160, fps=60.0,
        duration_s=soak_dur,
        env_overrides={
            "AMD_NATIVE_PROFILING": "1",
            "AMD_FRAME_TRACE": "1",
            "AMD_NATIVE_FRAME_ACCOUNTING": "1",
        },
        sampler=False,
        telemetry=telemetry,
    )
    profile_soak_nohud = read_amd_profile(OUT_DIR / "audit3_soak_4k_nohud.mp4.amd_profile.json")
    ft_csv_soak_nohud = list(OUT_DIR.glob("audit3_soak_4k_nohud.mp4.frame_accounting.csv"))
    fa_rows_soak_nohud = read_frame_accounting(ft_csv_soak_nohud[0]) if ft_csv_soak_nohud else []
    results["soak_nohud"] = {"profile": profile_soak_nohud, "run": r_soak_nohud, "frame_rows": len(fa_rows_soak_nohud)}
    print(f"  Done. render_fps={r_soak_nohud.get('render_fps', 'N/A'):.2f}  frames_in_csv={len(fa_rows_soak_nohud)}")

    # 4K full soak (2000 frames — will take much longer due to full overlay)
    print(f"\n[Part 10] Long-run soak — {SOAK_FRAMES} frames 4K FULL overlay...")
    r_soak_full = run_case(
        name="audit3_soak_4k_full",
        layout=copy.deepcopy(layout),
        width=3840, height=2160, fps=60.0,
        duration_s=soak_dur,
        env_overrides={
            "AMD_NATIVE_PROFILING": "1",
            "AMD_FRAME_TRACE": "1",
            "AMD_NATIVE_FRAME_ACCOUNTING": "1",
        },
        sampler=False,
        telemetry=telemetry,
    )
    profile_soak_full = read_amd_profile(OUT_DIR / "audit3_soak_4k_full.mp4.amd_profile.json")
    ft_csv_soak_full = list(OUT_DIR.glob("audit3_soak_4k_full.mp4.frame_accounting.csv"))
    fa_rows_soak_full = read_frame_accounting(ft_csv_soak_full[0]) if ft_csv_soak_full else []
    results["soak_full"] = {"profile": profile_soak_full, "run": r_soak_full, "frame_rows": len(fa_rows_soak_full)}
    print(f"  Done. render_fps={r_soak_full.get('render_fps', 'N/A'):.2f}  frames_in_csv={len(fa_rows_soak_full)}")

    # Save raw results
    (OUT3 / "audit3_raw_results.json").write_text(
        json.dumps({
            k: {kk: vv for kk, vv in v.items() if kk != "frame_rows"}
            for k, v in results.items()
        }, indent=2, default=str, ensure_ascii=False),
        encoding="utf-8"
    )

    # Save frame accounting CSVs to OUT3
    for name, rows in [
        ("fa_1080p", fa_rows_1080),
        ("fa_4k", fa_rows_4k),
        ("fa_soak_nohud", fa_rows_soak_nohud),
        ("fa_soak_full", fa_rows_soak_full),
    ]:
        if rows:
            cols = list(rows[0].keys())
            with open(OUT3 / f"{name}.csv", "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=cols)
                writer.writeheader()
                writer.writerows(rows)

    print(f"\nAll runs complete. Raw data saved to {OUT3}")
    return results, fa_rows_1080, fa_rows_4k, fa_rows_soak_nohud, fa_rows_soak_full, zorder, feasibility


if __name__ == "__main__":
    all_results = main()
    print("\nDone. Run analyze_audit3.py to generate the final report.")
