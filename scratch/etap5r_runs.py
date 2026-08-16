"""ETAP 5R — control runs A/B/C (spec sections 17/18).

A: AMD_NATIVE_FRAME_ACCOUNTING=0 (control).
B: AMD_NATIVE_FRAME_ACCOUNTING=1 (+ Python 5P accounting for cross-check).
C: AMD_NATIVE_FRAME_ACCOUNTING=1 (repeat, confirm reproducibility).

All runs: AMD_COMPOSE_5Q=OPTIMIZED, telemetry REFERENCE, 1131 frames,
full architecture (GPU_SPLIT charts + GPU gauge + GPU map LANCZOS).
Reports wall / TRUE FPS / instrumentation overhead.
"""
from __future__ import annotations

import json
import os
import statistics
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PY = r"c:/_DEV/TeleM/.venv-1/Scripts/python.exe"
RUNNER = ROOT / "scratch" / "run_etap5g_export.py"
OUT = ROOT / "Raporty" / "AMD_ETAP5G"


def _env(native_fa: bool, python_fa: bool) -> dict:
    env = dict(os.environ)
    for flag in ("AMD_GAUGE_AB_READBACK", "AMD_MAP_AB_READBACK", "AMD_CHART_AB_READBACK",
                 "AMD_CHART_STATIC_READBACK", "AMD_NATIVE_DIAGNOSTICS", "AMD_NATIVE_PROFILING",
                 "AMD_OVERLAY_PROFILE", "AMD_MAP_STATS", "AMD_TELEMETRY_MODE",
                 "AMD_FRAME_ACCOUNTING", "AMD_AMF_DIAG", "AMD_COMPOSE_5Q",
                 "AMD_NATIVE_FRAME_ACCOUNTING"):
        env.pop(flag, None)
    env["AMD_MAP_PATH"] = "GPU"
    env["AMD_MAP_FILTER"] = "LANCZOS"
    env["AMD_COMPOSE_5Q"] = "OPTIMIZED"
    if native_fa:
        env["AMD_NATIVE_FRAME_ACCOUNTING"] = "1"
    if python_fa:
        env["AMD_FRAME_ACCOUNTING"] = "1"
    return env


def _run(tag: str, native_fa: bool, python_fa: bool) -> dict:
    mp4 = OUT / f"l5r_{tag}.mp4"
    t0 = time.time()
    proc = subprocess.run(
        [PY, str(RUNNER), "--frames", "1131", "--chart-path", "GPU_SPLIT",
         "--gauge-path", "GPU", "--output", str(mp4)],
        cwd=str(ROOT), env=_env(native_fa, python_fa),
        capture_output=True, text=True,
    )
    wall = time.time() - t0
    profile = mp4.with_suffix(mp4.suffix + ".amd_profile.json")
    csv = mp4.with_suffix(mp4.suffix + ".frame_accounting.csv")
    if proc.returncode != 0 or not profile.exists():
        tail = "\n".join(proc.stdout.splitlines()[-20:])
        print(f"[{tag}] native_fa={native_fa} rc={proc.returncode} wall={wall:.2f}s FAIL\n{tail}",
              flush=True)
        return {"tag": tag, "wall": wall, "valid": False}
    d = json.loads(profile.read_text(encoding="utf-8"))
    fa = d.get("frame_accounting", {})
    e5l = d.get("etap5l", {})
    amf = d.get("amf", {})
    e5p = d.get("etap5p", {}) or {}
    python_pf = (e5p.get("stages", {}) or {}).get("process_frame", {}).get("median_ms")
    rec = {
        "tag": tag, "native_fa": native_fa, "python_fa": python_fa,
        "wall": wall, "true_fps": d.get("true_fps", 0.0),
        "python_process_frame_med": python_pf,
        "amf_input_full": amf.get("input_full_count", 0),
        "amf_retries": amf.get("retry_count", 0),
        "csv_exists": csv.exists(),
        "csv_frames": (len(csv.read_text(encoding="utf-8").splitlines()) - 1
                       if csv.exists() else 0),
        "valid": (fa.get("cadence_gpu") == 1131 and fa.get("hr_gpu") == 1131
                  and fa.get("map_gpu") == 1131
                  and e5l.get("gauge_gpu_frames") == 1131
                  and amf.get("dropped_submissions") == 0),
    }
    print(f"[{tag}] native_fa={native_fa} python_fa={python_fa} wall={wall:.2f}s "
          f"FPS={rec['true_fps']:.2f} csv={rec['csv_frames']} "
          f"input_full={rec['amf_input_full']} retries={rec['amf_retries']} "
          f"valid={rec['valid']}", flush=True)
    return rec


def main() -> int:
    runs = {}
    runs["A"] = _run("A", native_fa=False, python_fa=False)
    runs["B"] = _run("B", native_fa=True, python_fa=True)
    runs["C"] = _run("C", native_fa=True, python_fa=True)
    report = {"runs": runs, "order": ["A", "B", "C"]}
    if all(runs[t]["valid"] for t in ("A", "B", "C")):
        a_wall = runs["A"]["wall"]
        bc_wall = statistics.median([runs["B"]["wall"], runs["C"]["wall"]])
        overhead = (bc_wall - a_wall) / a_wall * 100.0
        report["overhead_pct"] = overhead
        print(f"\nInstrumentation overhead (BC-A)/A: {overhead:.2f}%", flush=True)
        print(f"  A wall={a_wall:.2f}s FPS={runs['A']['true_fps']:.2f}", flush=True)
        print(f"  B wall={runs['B']['wall']:.2f}s FPS={runs['B']['true_fps']:.2f}", flush=True)
        print(f"  C wall={runs['C']['wall']:.2f}s FPS={runs['C']['true_fps']:.2f}", flush=True)
    (OUT / "etap5r_control.json").write_text(json.dumps(report, indent=2, default=str),
                                             encoding="utf-8")
    print(f"\nJSON: {OUT / 'etap5r_control.json'}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
