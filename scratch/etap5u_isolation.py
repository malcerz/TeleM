"""ETAP 5U — isolation matrix (clean wall, gpu_ts=False).

Isolates:
  DRAIN_READY effect:  C vs A (pool4), D2 vs D1 (pool6), E2 vs E1 (pool8)
  Pool-size effect:    D1/E1 vs A (REFERENCE), D2/E2 vs C (DRAIN_READY)
  Repeatability:       A1 vs A2, C1 vs C2

A1,A2: ENCODE/pool4/REFERENCE
C1,C2: ENCODE/pool4/DRAIN_READY
D1:    ENCODE/pool6/REFERENCE
D2:    ENCODE/pool6/DRAIN_READY
E1:    ENCODE/pool8/REFERENCE
E2:    ENCODE/pool8/DRAIN_READY
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


def _env(pool: int, query: str) -> dict:
    env = dict(os.environ)
    for flag in ("AMD_GAUGE_AB_READBACK", "AMD_MAP_AB_READBACK", "AMD_CHART_AB_READBACK",
                 "AMD_CHART_STATIC_READBACK", "AMD_NATIVE_DIAGNOSTICS", "AMD_NATIVE_PROFILING",
                 "AMD_OVERLAY_PROFILE", "AMD_MAP_STATS", "AMD_TELEMETRY_MODE",
                 "AMD_FRAME_ACCOUNTING", "AMD_AMF_DIAG", "AMD_COMPOSE_5Q",
                 "AMD_NATIVE_FRAME_ACCOUNTING", "AMD_VP_STATE_MODE",
                 "AMD_GPU_TIMESTAMP_PROFILE", "AMD_AMF_MODE", "AMD_AMF_QUERY_MODE",
                 "AMD_VP_POOL_SIZE"):
        env.pop(flag, None)
    env["AMD_MAP_PATH"] = "GPU"
    env["AMD_MAP_FILTER"] = "LANCZOS"
    env["AMD_COMPOSE_5Q"] = "OPTIMIZED"
    env["AMD_VP_STATE_MODE"] = "REFERENCE"
    env["AMD_AMF_MODE"] = "ENCODE"
    env["AMD_VP_POOL_SIZE"] = str(pool)
    if query:
        env["AMD_AMF_QUERY_MODE"] = query
    return env


def _run(tag: str, pool: int, query: str) -> dict:
    mp4 = OUT / f"l5u_{tag}.mp4"
    t0 = time.time()
    proc = subprocess.run(
        [PY, str(RUNNER), "--frames", "1131", "--chart-path", "GPU_SPLIT",
         "--gauge-path", "GPU", "--output", str(mp4)],
        cwd=str(ROOT), env=_env(pool, query), capture_output=True, text=True,
    )
    wall = time.time() - t0
    profile = mp4.with_suffix(mp4.suffix + ".amd_profile.json")
    if proc.returncode != 0 or not profile.exists():
        tail = "\n".join(proc.stdout.splitlines()[-15:])
        print(f"[{tag}] rc={proc.returncode} wall={wall:.2f}s FAIL\n{tail}", flush=True)
        return {"tag": tag, "wall": wall, "valid": False}
    d = json.loads(profile.read_text(encoding="utf-8"))
    fa = d.get("frame_accounting", {})
    e5l = d.get("etap5l", {})
    amf = d.get("amf", {})
    submitted = fa.get("amf_submitted", 0)
    received = fa.get("amf_output", 0)
    rec = {
        "tag": tag, "pool": pool, "query": query or "REFERENCE",
        "wall": wall, "true_fps": d.get("true_fps", 0.0),
        "amf_submitted": submitted, "amf_received": received,
        "amf_outstanding": submitted - received,
        "input_full": amf.get("input_full_count", 0),
        "retries": amf.get("retry_count", 0),
        "dropped": amf.get("dropped_submissions", 0),
        "valid": (fa.get("cadence_gpu") == 1131 and fa.get("hr_gpu") == 1131
                  and fa.get("map_gpu") == 1131
                  and e5l.get("gauge_gpu_frames") == 1131
                  and amf.get("dropped_submissions") == 0),
    }
    print(f"[{tag}] pool={pool} query={query or 'REFERENCE'} wall={wall:.2f}s "
          f"FPS={rec['true_fps']:.2f} sub={submitted} rec={received} "
          f"iFull={rec['input_full']} valid={rec['valid']}", flush=True)
    return rec


def _med(name: str, runs: dict, tags) -> float:
    return statistics.median([runs[t]["true_fps"] for t in tags])


def main() -> int:
    runs = {}
    for tag, pool, query in [
        ("A1", 4, ""), ("A2", 4, ""),
        ("C1", 4, "DRAIN_READY"), ("C2", 4, "DRAIN_READY"),
        ("D1", 6, ""), ("D2", 6, "DRAIN_READY"),
        ("E1", 8, ""), ("E2", 8, "DRAIN_READY"),
    ]:
        runs[tag] = _run(tag, pool, query)
    report = {"runs": runs, "order": ["A1", "A2", "C1", "C2", "D1", "D2", "E1", "E2"]}
    if all(runs[t]["valid"] for t in runs):
        a = _med("A", runs, ["A1", "A2"])
        c = _med("C", runs, ["C1", "C2"])
        d1, d2 = runs["D1"]["true_fps"], runs["D2"]["true_fps"]
        e1, e2 = runs["E1"]["true_fps"], runs["E2"]["true_fps"]
        print("\n=== ETAP 5U isolation (FPS, med) ===", flush=True)
        print(f"  A pool4 REF   : {a:.2f}  (A1={runs['A1']['true_fps']:.2f} A2={runs['A2']['true_fps']:.2f})", flush=True)
        print(f"  C pool4 DRAIN : {c:.2f}  (C1={runs['C1']['true_fps']:.2f} C2={runs['C2']['true_fps']:.2f})", flush=True)
        print(f"  D1 pool6 REF  : {d1:.2f}", flush=True)
        print(f"  D2 pool6 DRAIN: {d2:.2f}", flush=True)
        print(f"  E1 pool8 REF  : {e1:.2f}", flush=True)
        print(f"  E2 pool8 DRAIN: {e2:.2f}", flush=True)
        print("\n  DRAIN_READY delta (REF-DRAIN):", flush=True)
        print(f"    pool4: {c - a:+.2f}", flush=True)
        print(f"    pool6: {d2 - d1:+.2f}", flush=True)
        print(f"    pool8: {e2 - e1:+.2f}", flush=True)
        print("  Pool-size delta (REF):", flush=True)
        print(f"    6 vs 4: {d1 - a:+.2f}", flush=True)
        print(f"    8 vs 4: {e1 - a:+.2f}", flush=True)
        print("  Pool-size delta (DRAIN):", flush=True)
        print(f"    6 vs 4: {d2 - c:+.2f}", flush=True)
        print(f"    8 vs 4: {e2 - c:+.2f}", flush=True)
    (OUT / "etap5u_isolation.json").write_text(json.dumps(report, indent=2, default=str),
                                               encoding="utf-8")
    print(f"\nJSON: {OUT / 'etap5u_isolation.json'}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
