"""TeleM AMD Render Path Audit 2 - CONTROL (AUDIT ONLY).

Continuation of RAPORT_AMD_RENDER_PATH_AUDIT.md.  Answers two questions:
  A) Full per-frame accounting for 4K full and 4K no-overlay (where does the
     wall time go; mean vs median of a heavy-tailed distribution).
  B) Why HR/Cadence charts still render on CPU/ABOVE with AMD_CHART_PATH=GPU_SPLIT
     in the real full layout (map split vs z-order guard).

Uses the production exporter with AMD_FRAME_TRACE=1 (per-frame CSV accounting),
AMD_NATIVE_FRAME_ACCOUNTING=1 (native substages), AMD_GPU_TIMESTAMP_PROFILE=1
(GPU timeline) and AMD_CHART_TRACE=1 (chart path decision).  No production
behavior is changed.
"""

from __future__ import annotations

import copy
import csv
import json
import os
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from run_amd_render_path_audit import (
    OUT_DIR, ROOT, SCRATCH, run_case, load_telemetry, family_subset,
    empty_layout, _BASE_ENV, _CLEAR_ENV,
)

OUT2 = ROOT / "Raporty" / "AMD_RENDER_PATH_AUDIT_2"
OUT2.mkdir(parents=True, exist_ok=True)


def layout_from_keys(base: dict, ordered_keys: list[str]) -> dict:
    """Build a layout containing only the given keys, in the given order."""
    out = copy.deepcopy(base)
    inds = {}
    for key in ordered_keys:
        if key in base.get("indicators", {}):
            inds[key] = copy.deepcopy(base["indicators"][key])
            inds[key]["enabled"] = True
    out["indicators"] = inds
    out["custom_texts"] = []
    return out


def run_and_aggregate(name: str, layout, w: int, h: int, fps: float,
                      duration_s: float, env: dict, telemetry,
                      sampler: bool = False) -> dict:
    r = run_case(name, layout, w, h, fps, duration_s, env,
                 sampler=sampler, telemetry=telemetry)
    return r


def main():
    only = None
    args = sys.argv[1:]
    if "--only" in args:
        i = args.index("--only")
        only = set(x.strip() for x in args[i + 1].split(","))
    layout, telemetry = load_telemetry()

    CHART_TRACE_ENV = {"AMD_CHART_TRACE": "1"}
    FRAME_TRACE_ENV = {"AMD_FRAME_TRACE": "1", "AMD_NATIVE_FRAME_ACCOUNTING": "1",
                       "AMD_GPU_TIMESTAMP_PROFILE": "1"}

    # Chart keys used in the control tests.
    HR = "fit_heart_rate_text"
    CAD = "fit_cadence_text"
    MAP = "track_map"
    # a cheap ABOVE-after-map element (iso_text is a text widget)
    POST = "iso_text"

    cases = []
    # ---- Part A: 4K full accounting (300 frames) ----
    cases.append(("account_4k_full_300f", copy.deepcopy(layout),
                  3840, 2160, 60.0, 5.0, FRAME_TRACE_ENV, True))
    # ---- Part A: 4K no-overlay accounting (300 frames) ----
    cases.append(("account_4k_nohud_300f", empty_layout(layout),
                  3840, 2160, 60.0, 5.0, FRAME_TRACE_ENV, True))
    # ---- Part B: chart path control matrix (1080p, 90 frames) ----
    cases.append(("test1_hr_only", layout_from_keys(layout, [HR]), 1920, 1080, 60.0, 1.5,
                  CHART_TRACE_ENV, False))
    cases.append(("test2_cadence_only", layout_from_keys(layout, [CAD]), 1920, 1080, 60.0, 1.5,
                  CHART_TRACE_ENV, False))
    cases.append(("test3_hr_cadence", layout_from_keys(layout, [HR, CAD]), 1920, 1080, 60.0, 1.5,
                  CHART_TRACE_ENV, False))
    cases.append(("test4_chart_before_map", layout_from_keys(layout, [HR, CAD, MAP]), 1920, 1080, 60.0, 1.5,
                  CHART_TRACE_ENV, False))
    cases.append(("test5_map_before_chart", layout_from_keys(layout, [MAP, HR, CAD]), 1920, 1080, 60.0, 1.5,
                  CHART_TRACE_ENV, False))
    cases.append(("test6_chart_elem_before_map", layout_from_keys(layout, [HR, CAD, POST, MAP]), 1920, 1080, 60.0, 1.5,
                  CHART_TRACE_ENV, False))
    cases.append(("test7_chart_elem_after_map", layout_from_keys(layout, [MAP, HR, CAD, POST]), 1920, 1080, 60.0, 1.5,
                  CHART_TRACE_ENV, False))
    cases.append(("test8_full_preset", copy.deepcopy(layout), 1920, 1080, 60.0, 1.5,
                  CHART_TRACE_ENV, False))
    # GPU_SPLIT working config (charts only, no map) - CPU vs GPU cost at 1080p
    cases.append(("gpu_charts_working", layout_from_keys(layout, [HR, CAD]), 1920, 1080, 60.0, 1.5,
                  CHART_TRACE_ENV, False))
    cases.append(("cpu_charts_reference", layout_from_keys(layout, [HR, CAD]), 1920, 1080, 60.0, 1.5,
                  {"AMD_CHART_PATH": "CPU_REFERENCE", "AMD_CHART_TRACE": "1"}, False))

    if only:
        cases = [c for c in cases if c[0] in only]

    results = []
    summary_path = OUT2 / "audit2_summary.json"
    existing = {}
    if summary_path.exists():
        try:
            existing = {r["name"]: r for r in json.load(open(summary_path, encoding="utf-8"))}
        except Exception:
            existing = {}

    for name, lay, w, h, fps, dur, env, sampl in cases:
        if name in existing and only is None:
            print(f"[AUDIT2] skipping existing {name}", flush=True)
            results.append(existing[name])
            continue
        print(f"\n[AUDIT2] === CASE {name}  {w}x{h} @ {fps}fps {int(dur*fps)} frames ===", flush=True)
        r = run_and_aggregate(name, lay, w, h, fps, dur, env, telemetry, sampler=sampl)
        results.append(r)
        merged = {**existing, **{r["name"]: r for r in results}}
        with open(summary_path, "w", encoding="utf-8") as f:
            json.dump(list(merged.values()), f, indent=2, ensure_ascii=False)
        print(f"[AUDIT2] {name} done ok={r['ok']} wall={r['wall_s']}s "
              f"render_fps={r.get('profile',{}).get('render_fps')}", flush=True)

    print(f"\n[AUDIT2] summary: {summary_path}")


if __name__ == "__main__":
    main()
