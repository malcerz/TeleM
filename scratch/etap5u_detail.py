"""ETAP 5U — detailed per-frame runs (native accounting + GPU timeline).

N4: ENCODE/pool4/REFERENCE
N8: ENCODE/pool8/REFERENCE

Analyzes frame_accounting.csv (first-call wait, AMF outstanding, pool index,
query calls) + gpu_timeline.csv (GPU span/cadence) + lifecycle reuse.
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


def _env(pool: int, native_fa: bool, gpu_ts: bool) -> dict:
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
    if native_fa:
        env["AMD_NATIVE_FRAME_ACCOUNTING"] = "1"
    if gpu_ts:
        env["AMD_GPU_TIMESTAMP_PROFILE"] = "1"
    return env


def _pct(vals, p):
    sv = sorted(vals)
    if not sv:
        return 0.0
    return sv[min(len(sv) - 1, int(round(p / 100.0 * (len(sv) - 1))))]


def analyze(tag: str, pool: int) -> dict:
    mp4 = OUT / f"l5u_{tag}.mp4"
    t0 = time.time()
    proc = subprocess.run(
        [PY, str(RUNNER), "--frames", "1131", "--chart-path", "GPU_SPLIT",
         "--gauge-path", "GPU", "--output", str(mp4)],
        cwd=str(ROOT), env=_env(pool, native_fa=True, gpu_ts=True), capture_output=True, text=True,
    )
    wall = time.time() - t0
    profile = mp4.with_suffix(mp4.suffix + ".amd_profile.json")
    facsv = mp4.with_suffix(mp4.suffix + ".frame_accounting.csv")
    gtlcsv = mp4.with_suffix(mp4.suffix + ".gpu_timeline.csv")
    if proc.returncode != 0 or not profile.exists() or not facsv.exists():
        print(f"[{tag}] FAIL rc={proc.returncode} profile={profile.exists()} "
              f"fa={facsv.exists()}\n{proc.stdout.splitlines()[-8:]}", flush=True)
        return {"tag": tag, "valid": False}
    d = json.loads(profile.read_text(encoding="utf-8"))
    fa = d.get("frame_accounting", {})
    amf = d.get("amf", {})
    # per-frame trace
    rows = list(csv.DictReader(facsv.open(encoding="utf-8")))
    query_ms = [float(r["amf_query"]) for r in rows]
    proc_ms = [float(r["process_frame_total"]) for r in rows]
    received = [int(r["amf_received"]) for r in rows]
    submitted = [int(r["amf_submitted"]) for r in rows]
    outstanding = [s - rr for s, rr in zip(submitted, received)]
    pool_idx = [int(r["pool_index"]) for r in rows]
    # first-call wait: frames until first AMF packet received
    first_rec = next((i for i, r in enumerate(received) if r > 0), None)
    # query calls distribution
    qcalls = [int(r["amf_query_calls"]) for r in rows]
    outputs = [int(r["amf_outputs"]) for r in rows]
    # GPU timeline
    span = []
    cad = []
    if gtlcsv.exists():
        grow = list(csv.DictReader(gtlcsv.open(encoding="utf-8")))
        span = [float(r["span_ms"]) for r in grow if r.get("span_ms")]
        # cadence from begin timestamps (raw ticks, freq 1e8 -> ms)
        begins = [float(r["begin_ts"]) for r in grow if r.get("begin_ts")]
        freq = float(grow[0]["freq"]) if grow and grow[0].get("freq") else 1e8
        if len(begins) > 1:
            cad = [(b - a) / freq * 1000.0 for a, b in zip(begins, begins[1:])]
    rec = {
        "tag": tag, "pool": pool, "wall": wall, "true_fps": d.get("true_fps", 0.0),
        "frames": len(rows),
        "first_packet_frame": first_rec if first_rec is not None else -1,
        "first_call_wait_ms": (rows[first_rec]["process_frame_total"]
                               if first_rec is not None else None),
        "amf_query_ms": {"med": _pct(query_ms, 50), "p95": _pct(query_ms, 95),
                         "p99": _pct(query_ms, 99), "max": max(query_ms)},
        "amf_outstanding": {"med": _pct(outstanding, 50), "max": max(outstanding),
                            "p95": _pct(outstanding, 95)},
        "process_frame_ms": {"med": _pct(proc_ms, 50), "p95": _pct(proc_ms, 95),
                             "p99": _pct(proc_ms, 99)},
        "query_calls_per_frame": {"med": _pct(qcalls, 50), "max": max(qcalls)},
        "outputs_per_frame": {"med": _pct(outputs, 50), "max": max(outputs)},
        "pool_index": {"med": _pct(pool_idx, 50), "min": min(pool_idx), "max": max(pool_idx)},
        "gpu_span_ms": {"med": _pct(span, 50), "p95": _pct(span, 95), "max": max(span) if span else 0},
        "gpu_cadence_ms": {"med": _pct(cad, 50), "p95": _pct(cad, 95), "p99": _pct(cad, 99)} if cad else {},
        "gpu_cadence_fps": (1000.0 / _pct(cad, 50)) if cad else 0.0,
        "input_full": amf.get("input_full_count", 0),
        "dropped": amf.get("dropped_submissions", 0),
        "valid": (fa.get("cadence_gpu") == 1131 and fa.get("hr_gpu") == 1131
                  and amf.get("dropped_submissions") == 0),
    }
    print(json.dumps(rec, indent=2, default=str), flush=True)
    return rec


def main() -> int:
    report = {"N4": analyze("N4", 4), "N8": analyze("N8", 8)}
    (OUT / "etap5u_detail.json").write_text(json.dumps(report, indent=2, default=str),
                                            encoding="utf-8")
    print(f"\nJSON: {OUT / 'etap5u_detail.json'}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
