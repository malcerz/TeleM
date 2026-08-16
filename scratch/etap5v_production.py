"""ETAP 5V — production performance A/B/C/D + 5Q cache wall effect (spec 16/28).

A: pool4 (AMD_COMPOSE_5Q=OPTIMIZED)
B: pool8 (AMD_COMPOSE_5Q=OPTIMIZED)
C: pool4 (repeat)
D: pool8 (repeat)
Q1: pool8 (AMD_COMPOSE_5Q=REFERENCE)  -> 5Q cache wall effect at pool8

1131 frames, profiling OFF, diagnostics OFF, readbacks OFF, GPU-ts OFF.
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


def _env(pool: int, compose: str) -> dict:
    env = dict(os.environ)
    for flag in ("AMD_GAUGE_AB_READBACK", "AMD_MAP_AB_READBACK", "AMD_CHART_AB_READBACK",
                 "AMD_CHART_STATIC_READBACK", "AMD_NATIVE_DIAGNOSTICS", "AMD_NATIVE_PROFILING",
                 "AMD_OVERLAY_PROFILE", "AMD_MAP_STATS", "AMD_TELEMETRY_MODE",
                 "AMD_FRAME_ACCOUNTING", "AMD_AMF_DIAG", "AMD_COMPOSE_5Q",
                 "AMD_NATIVE_FRAME_ACCOUNTING", "AMD_VP_STATE_MODE",
                 "AMD_GPU_TIMESTAMP_PROFILE", "AMD_AMF_MODE", "AMD_AMF_QUERY_MODE",
                 "AMD_VP_POOL_SIZE", "AMD_POOL_LIFECYCLE_STATS"):
        env.pop(flag, None)
    env["AMD_MAP_PATH"] = "GPU"
    env["AMD_MAP_FILTER"] = "LANCZOS"
    env["AMD_COMPOSE_5Q"] = compose
    env["AMD_VP_STATE_MODE"] = "REFERENCE"
    env["AMD_VP_POOL_SIZE"] = str(pool)
    return env


def _run(tag: str, pool: int, compose: str) -> dict:
    mp4 = OUT / f"l5v_{tag}.mp4"
    t0 = time.time()
    proc = subprocess.run(
        [PY, str(RUNNER), "--frames", "1131", "--chart-path", "GPU_SPLIT",
         "--gauge-path", "GPU", "--output", str(mp4)],
        cwd=str(ROOT), env=_env(pool, compose), capture_output=True, text=True,
    )
    wall = time.time() - t0
    profile = mp4.with_suffix(mp4.suffix + ".amd_profile.json")
    if proc.returncode != 0 or not profile.exists():
        print(f"[{tag}] FAIL rc={proc.returncode} wall={wall:.2f}s\n"
              f"{proc.stdout.splitlines()[-8:]}", flush=True)
        return {"tag": tag, "pool": pool, "compose": compose, "wall": wall, "valid": False}
    d = json.loads(profile.read_text(encoding="utf-8"))
    fa = d.get("frame_accounting", {})
    e5l = d.get("etap5l", {})
    amf = d.get("amf", {})
    rec = {
        "tag": tag, "pool": pool, "compose": compose, "wall": wall,
        "true_fps": d.get("true_fps", 0.0),
        "muxed": fa.get("muxed_frames", 0),
        "amf_submitted": fa.get("amf_submitted", 0),
        "amf_output": fa.get("amf_output", 0),
        "input_full": amf.get("input_full_count", 0),
        "dropped": amf.get("dropped_submissions", 0),
        "valid": (fa.get("muxed_frames") == 1131 and fa.get("cadence_gpu") == 1131
                  and fa.get("hr_gpu") == 1131 and fa.get("map_gpu") == 1131
                  and e5l.get("gauge_gpu_frames") == 1131
                  and amf.get("dropped_submissions") == 0),
    }
    print(f"[{tag}] pool={pool} compose={compose} wall={wall:.2f}s FPS={rec['true_fps']:.2f} "
          f"muxed={rec['muxed']} iFull={rec['input_full']} valid={rec['valid']}", flush=True)
    return rec


def main() -> int:
    runs = {}
    for tag, pool, compose in [
        ("A", 4, "OPTIMIZED"), ("B", 8, "OPTIMIZED"),
        ("C", 4, "OPTIMIZED"), ("D", 8, "OPTIMIZED"),
        ("Q1", 8, "REFERENCE"),
    ]:
        runs[tag] = _run(tag, pool, compose)
    report = {"runs": runs, "order": ["A", "B", "C", "D", "Q1"]}
    if all(runs[t]["valid"] for t in ("A", "B", "C", "D", "Q1")):
        p4 = statistics.median([runs["A"]["true_fps"], runs["C"]["true_fps"]])
        p8 = statistics.median([runs["B"]["true_fps"], runs["D"]["true_fps"]])
        w4 = statistics.median([runs["A"]["wall"], runs["C"]["wall"]])
        w8 = statistics.median([runs["B"]["wall"], runs["D"]["wall"]])
        opt = statistics.median([runs["B"]["true_fps"], runs["D"]["true_fps"]])
        ref = runs["Q1"]["true_fps"]
        report["pool4"] = {"fps_median": p4, "wall_median": w4,
                           "runs": [runs["A"]["true_fps"], runs["C"]["true_fps"]]}
        report["pool8"] = {"fps_median": p8, "wall_median": w8,
                           "runs": [runs["B"]["true_fps"], runs["D"]["true_fps"]]}
        report["gain_pct"] = (p8 - p4) / p4 * 100.0
        report["gain_fps"] = p8 - p4
        report["compose_5q_at_pool8"] = {"REF": ref, "OPT": opt, "delta": opt - ref}
        print("\n=== ETAP 5V production ===", flush=True)
        print(f"  pool4: {runs['A']['true_fps']:.2f} / {runs['C']['true_fps']:.2f} "
              f"-> med {p4:.2f} FPS (wall {w4:.2f}s)", flush=True)
        print(f"  pool8: {runs['B']['true_fps']:.2f} / {runs['D']['true_fps']:.2f} "
              f"-> med {p8:.2f} FPS (wall {w8:.2f}s)", flush=True)
        print(f"  GAIN: {p8 - p4:+.2f} FPS ({100*(p8-p4)/p4:+.1f}%)", flush=True)
        print(f"  5Q @pool8: REF={ref:.2f} vs OPT={opt:.2f} delta={opt-ref:+.2f}", flush=True)
    (OUT / "etap5v_production.json").write_text(json.dumps(report, indent=2, default=str),
                                                encoding="utf-8")
    print(f"\nJSON: {OUT / 'etap5v_production.json'}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
