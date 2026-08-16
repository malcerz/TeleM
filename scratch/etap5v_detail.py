"""ETAP 5V — detail: process_frame / first-call / outstanding (spec 19-21)
+ clean production-default median (pool8, compose REFERENCE, no env).

P4d: pool4 + native accounting
P8d: pool8 + native accounting
Prod1/Prod2: production default (AMD_VP_POOL_SIZE unset -> 8, AMD_COMPOSE_5Q
             unset -> REFERENCE), accounting OFF -> clean FPS/wall.
"""
from __future__ import annotations

import csv
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


def _env(pool, native_fa: bool, set_compose: bool) -> dict:
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
    env["AMD_VP_STATE_MODE"] = "REFERENCE"
    if pool is not None:
        env["AMD_VP_POOL_SIZE"] = str(pool)
    if set_compose:
        env["AMD_COMPOSE_5Q"] = "OPTIMIZED"
    if native_fa:
        env["AMD_NATIVE_FRAME_ACCOUNTING"] = "1"
    return env


def _pct(vals, p):
    sv = sorted(vals)
    if not sv:
        return 0.0
    return sv[min(len(sv) - 1, int(round(p / 100.0 * (len(sv) - 1))))]


def _run(tag: str, pool, native_fa: bool, set_compose: bool) -> dict:
    mp4 = OUT / f"l5v_{tag}.mp4"
    t0 = time.time()
    proc = subprocess.run(
        [PY, str(RUNNER), "--frames", "1131", "--chart-path", "GPU_SPLIT",
         "--gauge-path", "GPU", "--output", str(mp4)],
        cwd=str(ROOT), env=_env(pool, native_fa, set_compose), capture_output=True, text=True,
    )
    wall = time.time() - t0
    profile = mp4.with_suffix(mp4.suffix + ".amd_profile.json")
    if proc.returncode != 0 or not profile.exists():
        print(f"[{tag}] FAIL rc={proc.returncode} wall={wall:.2f}s\n"
              f"{proc.stdout.splitlines()[-8:]}", flush=True)
        return {"tag": tag, "wall": wall, "valid": False}
    d = json.loads(profile.read_text(encoding="utf-8"))
    fa = d.get("frame_accounting", {})
    amf = d.get("amf", {})
    rec = {
        "tag": tag, "pool": pool, "wall": wall, "true_fps": d.get("true_fps", 0.0),
        "muxed": fa.get("muxed_frames", 0),
        "amf_submitted": fa.get("amf_submitted", 0),
        "amf_output": fa.get("amf_output", 0),
        "input_full": amf.get("input_full_count", 0),
        "dropped": amf.get("dropped_submissions", 0),
        "valid": (fa.get("muxed_frames") == 1131 and amf.get("dropped_submissions") == 0),
    }
    # per-frame analysis if native accounting was on
    facsv = mp4.with_suffix(mp4.suffix + ".frame_accounting.csv")
    if native_fa and facsv.exists():
        rows = list(csv.DictReader(facsv.open(encoding="utf-8")))
        pf = [float(r["process_frame_total"]) for r in rows]
        setup = [float(r["vp_setup"]) for r in rows]
        submitted = [int(r["amf_submitted"]) for r in rows]
        received = [int(r["amf_received"]) for r in rows]
        outstanding = [s - rr for s, rr in zip(submitted, received)]
        qms = [float(r["amf_query"]) for r in rows]
        rec["process_frame_ms"] = {"med": _pct(pf, 50), "p95": _pct(pf, 95),
                                   "p99": _pct(pf, 99)}
        # first D3D11 call of the frame = vp_setup (pool+CreateView+SetStream*)
        rec["first_d3d11_wait_ms"] = {"med": _pct(setup, 50), "p95": _pct(setup, 95),
                                      "p99": _pct(setup, 99)}
        rec["amf_outstanding"] = {"med": _pct(outstanding, 50), "max": max(outstanding)}
        rec["amf_query_ms"] = {"med": _pct(qms, 50)}
        rec["frames_pf_gt_10ms"] = sum(1 for x in pf if x > 10.0)
    print(f"[{tag}] pool={pool} wall={wall:.2f}s FPS={rec['true_fps']:.2f} "
          f"valid={rec['valid']}", flush=True)
    if "process_frame_ms" in rec:
        print(f"    process_frame med={rec['process_frame_ms']['med']:.2f} "
              f"p95={rec['process_frame_ms']['p95']:.2f} p99={rec['process_frame_ms']['p99']:.2f}"
              f" | >10ms frames={rec['frames_pf_gt_10ms']}/1131", flush=True)
        print(f"    first-d3d11(setup) med={rec['first_d3d11_wait_ms']['med']:.2f} "
              f"p95={rec['first_d3d11_wait_ms']['p95']:.2f} "
              f"p99={rec['first_d3d11_wait_ms']['p99']:.2f}", flush=True)
        print(f"    AMF outstanding med={rec['amf_outstanding']['med']} "
              f"max={rec['amf_outstanding']['max']} query med={rec['amf_query_ms']['med']:.3f}",
              flush=True)
    return rec


def main() -> int:
    runs = {}
    runs["P4d"] = _run("P4d", 4, native_fa=True, set_compose=True)
    runs["P8d"] = _run("P8d", 8, native_fa=True, set_compose=True)
    runs["Prod1"] = _run("Prod1", None, native_fa=False, set_compose=False)
    runs["Prod2"] = _run("Prod2", None, native_fa=False, set_compose=False)
    report = {"runs": runs}
    if all(runs[t]["valid"] for t in runs):
        med = statistics.median([runs["Prod1"]["true_fps"], runs["Prod2"]["true_fps"]])
        wall = statistics.median([runs["Prod1"]["wall"], runs["Prod2"]["wall"]])
        report["production_default"] = {
            "config": "pool8(default) + compose REFERENCE(default), no env",
            "fps": [runs["Prod1"]["true_fps"], runs["Prod2"]["true_fps"]],
            "fps_median": med, "wall_median": wall,
            "realtime_factor": med / (30000.0 / 1001.0),
            "realtime_margin_pct": (med / (30000.0 / 1001.0) - 1.0) * 100.0,
        }
        print("\n=== ETAP 5V production default (pool8 + REF) ===", flush=True)
        print(f"  Prod1={runs['Prod1']['true_fps']:.2f} Prod2={runs['Prod2']['true_fps']:.2f} "
              f"-> med {med:.2f} FPS (wall {wall:.2f}s)", flush=True)
        print(f"  realtime factor {med / (30000.0 / 1001.0):.3f}x, "
              f"margin {report['production_default']['realtime_margin_pct']:+.1f}%", flush=True)
    (OUT / "etap5v_detail.json").write_text(json.dumps(report, indent=2, default=str),
                                            encoding="utf-8")
    print(f"\nJSON: {OUT / 'etap5v_detail.json'}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
