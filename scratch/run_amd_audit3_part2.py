"""TeleM AMD Render Path Audit 3 — Part 2: remaining benchmark runs.

Picks up after audit3_above_1080p.mp4 (already done).
Runs: 4K full, GPU_SPLIT trace, chart compare 1080p+4K, soak 2000f.
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
WARMUP_FRAMES = 30
MEASURE_FRAMES = 300
SOAK_FRAMES = 2000
DUR_300 = (WARMUP_FRAMES + MEASURE_FRAMES) / 60.0

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


def safe_fps(r):
    p = r.get("profile", {})
    v = p.get("render_fps") if p else None
    if v is None:
        return "N/A"
    try:
        return f"{float(v):.2f}"
    except (ValueError, TypeError):
        return str(v)


def main():
    print("=" * 70)
    print("AMD Audit 3 — Part 2: remaining benchmark runs")
    print("=" * 70)

    layout, telemetry = load_telemetry()

    HR = "fit_heart_rate_text"
    CAD = "fit_cadence_text"

    # ── 1. 4K full (300 measured frames) ────────────────────────────────
    print("\n[Run 1/8] 4K full overlay (300 measured frames)...")
    r_4k = run_case(
        name="audit3_above_4k",
        layout=copy.deepcopy(layout),
        width=3840, height=2160, fps=60.0,
        duration_s=DUR_300,
        env_overrides=FULL_DIAG_ENV,
        sampler=False,
        telemetry=telemetry,
    )
    print(f"  4K full done. render_fps={safe_fps(r_4k)}")

    # ── 2. GPU_SPLIT chart path trace: full preset ───────────────────────
    print("\n[Run 2/8] GPU_SPLIT trace — full preset 1080p (90 frames)...")
    r_trace = run_case(
        name="audit3_chart_trace_full",
        layout=copy.deepcopy(layout),
        width=1920, height=1080, fps=60.0,
        duration_s=1.5,
        env_overrides={**CHART_TRACE_ENV, "AMD_NATIVE_FRAME_ACCOUNTING": "1"},
        sampler=False,
        telemetry=telemetry,
    )
    print(f"  Chart trace done. render_fps={safe_fps(r_trace)}")

    # ── 3. GPU_SPLIT isolated HR+CAD (confirm GPU works) ────────────────
    print("\n[Run 3/8] GPU_SPLIT isolated HR+CAD 1080p (90 frames)...")
    r_gpu_split = run_case(
        name="audit3_gpu_split_hr_cad",
        layout=layout_from_keys(layout, [HR, CAD]),
        width=1920, height=1080, fps=60.0,
        duration_s=1.5,
        env_overrides={**CHART_TRACE_ENV, "AMD_NATIVE_PROFILING": "1"},
        sampler=False,
        telemetry=telemetry,
    )
    print(f"  GPU_SPLIT isolated done. render_fps={safe_fps(r_gpu_split)}")

    # ── 4. CPU_REFERENCE HR+CAD 1080p (300 frames) ──────────────────────
    print("\n[Run 4/8] CPU_REFERENCE HR+CAD 1080p (300 measured frames)...")
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
    print(f"  CPU_REFERENCE 1080p done. render_fps={safe_fps(r_cpu_1080)}")

    # ── 5. GPU_SPLIT HR+CAD 1080p (300 frames) ──────────────────────────
    print("\n[Run 5/8] GPU_SPLIT HR+CAD 1080p (300 measured frames)...")
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
    print(f"  GPU_SPLIT 1080p done. render_fps={safe_fps(r_gpu_1080)}")

    # ── 6. CPU_REFERENCE HR+CAD 4K (300 frames) ─────────────────────────
    print("\n[Run 6/8] CPU_REFERENCE HR+CAD 4K (300 measured frames)...")
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
    print(f"  CPU_REFERENCE 4K done. render_fps={safe_fps(r_cpu_4k)}")

    # ── 7. GPU_SPLIT HR+CAD 4K (300 frames) ─────────────────────────────
    print("\n[Run 7/8] GPU_SPLIT HR+CAD 4K (300 measured frames)...")
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
    print(f"  GPU_SPLIT 4K done. render_fps={safe_fps(r_gpu_4k)}")

    # ── 8. Soak 2000 frames 4K no-overlay ───────────────────────────────
    soak_dur = SOAK_FRAMES / 60.0
    print(f"\n[Run 8/8] Soak 4K no-overlay ({SOAK_FRAMES} frames, {soak_dur:.0f}s video)...")
    r_soak = run_case(
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
    print(f"  Soak done. render_fps={safe_fps(r_soak)}")

    # Summary
    print("\n" + "=" * 70)
    print("All runs complete!")
    all_results = {
        "4k_full": r_4k,
        "chart_trace_full": r_trace,
        "gpu_split_hr_cad": r_gpu_split,
        "cpu_ref_1080p": r_cpu_1080,
        "gpu_split_1080p": r_gpu_1080,
        "cpu_ref_4k": r_cpu_4k,
        "gpu_split_4k": r_gpu_4k,
        "soak_4k_nohud": r_soak,
    }
    (OUT3 / "audit3_run_results.json").write_text(
        json.dumps(all_results, indent=2, default=str, ensure_ascii=False),
        encoding="utf-8"
    )
    print(f"Results saved to {OUT3 / 'audit3_run_results.json'}")
    return all_results


if __name__ == "__main__":
    main()
