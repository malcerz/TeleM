"""ETAP 5P — frame accounting runs.

A: accounting OFF (control).  B/C: accounting ON (REFERENCE telemetry).
D: accounting ON + PRECOMPUTED telemetry (5N explanation).
Reports wall / TRUE FPS / instrumentation overhead / accounting summary.
"""
from __future__ import annotations

import json
import os
import statistics
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

PY = r"c:/_DEV/TeleM/.venv-1/Scripts/python.exe"
RUNNER = ROOT / "scratch" / "run_etap5g_export.py"
OUT = ROOT / "Raporty" / "AMD_ETAP5G"
SOURCE_FPS = 29.97


def _env(accounting: bool, telemetry: str, amf_diag: bool) -> dict:
    env = dict(os.environ)
    for flag in ("AMD_GAUGE_AB_READBACK", "AMD_MAP_AB_READBACK", "AMD_CHART_AB_READBACK",
                 "AMD_CHART_STATIC_READBACK", "AMD_NATIVE_DIAGNOSTICS", "AMD_NATIVE_PROFILING",
                 "AMD_OVERLAY_PROFILE", "AMD_MAP_STATS", "AMD_TELEMETRY_MODE",
                 "AMD_FRAME_ACCOUNTING", "AMD_AMF_DIAG"):
        env.pop(flag, None)
    env["AMD_MAP_PATH"] = "GPU"
    env["AMD_MAP_FILTER"] = "LANCZOS"
    env["AMD_TELEMETRY_MODE"] = telemetry
    if accounting:
        env["AMD_FRAME_ACCOUNTING"] = "1"
    if amf_diag:
        env["AMD_AMF_DIAG"] = "1"
    return env


def _run(tag: str, accounting: bool, telemetry: str, amf_diag: bool) -> dict:
    mp4 = OUT / f"l5p_{tag}.mp4"
    t0 = time.time()
    proc = subprocess.run(
        [PY, str(RUNNER), "--frames", "1131", "--chart-path", "GPU_SPLIT",
         "--gauge-path", "GPU", "--output", str(mp4)],
        cwd=str(ROOT), env=_env(accounting, telemetry, amf_diag),
        capture_output=True, text=True,
    )
    wall = time.time() - t0
    profile = mp4.with_suffix(mp4.suffix + ".amd_profile.json")
    if proc.returncode != 0 or not profile.exists():
        tail = "\n".join(proc.stdout.splitlines()[-20:])
        print(f"[{tag}] rc={proc.returncode} wall={wall:.2f}s FAIL\n{tail}", flush=True)
        return {"tag": tag, "wall": wall, "valid": False}
    d = json.loads(profile.read_text(encoding="utf-8"))
    fa = d["frame_accounting"]
    e5p = d.get("etap5p", {})
    rec = {
        "tag": tag, "wall": wall, "true_fps": d.get("true_fps", 0.0),
        "accounting": e5p,
        "valid": (fa.get("cadence_gpu") == 1131 and fa.get("hr_gpu") == 1131
                  and fa.get("map_gpu") == 1131
                  and d.get("etap5l", {}).get("gauge_gpu_frames") == 1131
                  and d.get("amf", {}).get("dropped_submissions") == 0),
    }
    print(f"[{tag}] acct={accounting} tel={telemetry} wall={wall:.2f}s FPS={rec['true_fps']:.2f} "
          f"valid={rec['valid']}", flush=True)
    return rec


def main() -> int:
    A = _run("A", accounting=False, telemetry="REFERENCE", amf_diag=False)
    B = _run("B", accounting=True, telemetry="REFERENCE", amf_diag=True)
    C = _run("C", accounting=True, telemetry="REFERENCE", amf_diag=True)
    D = _run("D", accounting=True, telemetry="PRECOMPUTED", amf_diag=True)
    report = {"runs": {"A": A, "B": B, "C": C, "D": D}}
    if A.get("valid") and B.get("valid"):
        overhead = (B["wall"] - A["wall"]) / A["wall"] * 100.0
        report["instrumentation_overhead_pct"] = overhead
        print(f"\nInstrumentation overhead (B-A)/A: {overhead:.2f}%", flush=True)
    for tag in ("B", "C", "D"):
        e = report["runs"][tag].get("accounting") or {}
        if e.get("enabled"):
            print(f"\n[{tag}] ACCOUNTING", flush=True)
            print(f"  frame_total med={e['frame_total_ms']['median']:.3f} "
                  f"p95={e['frame_total_ms']['p95']:.3f} p99={e['frame_total_ms']['p99']:.3f}",
                  flush=True)
            print(f"  measured med={e['measured_sum_median_ms']:.3f} "
                  f"unaccounted med={e['unaccounted_ms']['median']:.3f} "
                  f"({e['unaccounted_ms']['pct_of_frame']:.2f}%) "
                  f"accounted={e['accounted_pct']:.2f}%", flush=True)
            top = sorted(e["stages"].items(), key=lambda kv: -kv[1]["median_ms"])[:6]
            for name, s in top:
                print(f"    {name:16s} med={s['median_ms']:7.3f} p95={s['p95_ms']:7.3f}", flush=True)
    (OUT / "etap5p_runs.json").write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print(f"\nJSON: {OUT / 'etap5p_runs.json'}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
