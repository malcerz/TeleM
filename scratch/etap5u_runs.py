"""ETAP 5U — encoder feed / query policy / pool size test matrix (spec 22).

A: ENCODE / pool4 / QUERY_REFERENCE   (baseline)
B: BYPASS / pool4                     (frontend-only ceiling, no encode)
C: ENCODE / pool4 / DRAIN_READY       (drain all immediately-ready packets)
D: ENCODE / pool6 / DRAIN_READY
E: ENCODE / pool8 / DRAIN_READY

All: AMD_VP_STATE_MODE=REFERENCE, AMD_COMPOSE_5Q=OPTIMIZED, telemetry REFERENCE,
map GPU/LANCZOS, chart GPU_SPLIT, gauge GPU.  1131 frames each.

Answers (spec 29): is VCN really slower, or does our feed/query/resource
lifecycle artificially throttle throughput?
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


def _env(amf_mode: str, pool: int, query: str, gpu_ts: bool) -> dict:
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
    env["AMD_AMF_MODE"] = amf_mode
    env["AMD_VP_POOL_SIZE"] = str(pool)
    if query:
        env["AMD_AMF_QUERY_MODE"] = query
    if gpu_ts:
        env["AMD_GPU_TIMESTAMP_PROFILE"] = "1"
    return env


def _run(tag: str, amf_mode: str, pool: int, query: str, gpu_ts: bool) -> dict:
    mp4 = OUT / f"l5u_{tag}.mp4"
    t0 = time.time()
    proc = subprocess.run(
        [PY, str(RUNNER), "--frames", "1131", "--chart-path", "GPU_SPLIT",
         "--gauge-path", "GPU", "--output", str(mp4)],
        cwd=str(ROOT), env=_env(amf_mode, pool, query, gpu_ts), capture_output=True, text=True,
    )
    wall = time.time() - t0
    profile = mp4.with_suffix(mp4.suffix + ".amd_profile.json")
    gtl = mp4.with_suffix(mp4.suffix + ".gpu_timeline.csv")
    if proc.returncode != 0 or not profile.exists():
        tail = "\n".join(proc.stdout.splitlines()[-15:])
        print(f"[{tag}] rc={proc.returncode} wall={wall:.2f}s FAIL\n{tail}", flush=True)
        return {"tag": tag, "wall": wall, "valid": False}
    d = json.loads(profile.read_text(encoding="utf-8"))
    fa = d.get("frame_accounting", {})
    e5l = d.get("etap5l", {})
    amf = d.get("amf", {})
    gpu_frames = len(gtl.read_text(encoding="utf-8").splitlines()) - 1 if gtl.exists() else 0
    submitted = fa.get("amf_submitted", 0)
    received = fa.get("amf_output", 0)
    rec = {
        "tag": tag, "amf_mode": amf_mode, "pool": pool, "query": query, "gpu_ts": gpu_ts,
        "wall": wall, "true_fps": d.get("true_fps", 0.0),
        "gpu_timeline_frames": gpu_frames,
        "amf_submitted": submitted, "amf_received": received,
        "amf_outstanding": submitted - received,
        "input_full": amf.get("input_full_count", 0),
        "retries": amf.get("retry_count", 0),
        "dropped": amf.get("dropped_submissions", 0),
        "vp_processed": fa.get("vp_processed", 0),
        "valid": (fa.get("cadence_gpu") == 1131 and fa.get("hr_gpu") == 1131
                  and fa.get("map_gpu") == 1131
                  and e5l.get("gauge_gpu_frames") == 1131
                  and amf.get("dropped_submissions") == 0),
    }
    if amf_mode == "BYPASS":
        rec["valid"] = (fa.get("vp_processed") == 1131 and amf.get("dropped_submissions") == 0)
    print(f"[{tag}] mode={amf_mode} pool={pool} query={query or 'REFERENCE'} "
          f"gpu_ts={gpu_ts} wall={wall:.2f}s FPS={rec['true_fps']:.2f} "
          f"sub={submitted} rec={received} out={rec['amf_outstanding']} "
          f"iFull={rec['input_full']} gpu_tl={gpu_frames} valid={rec['valid']}", flush=True)
    return rec


def main() -> int:
    runs = {}
    runs["A"] = _run("A", amf_mode="ENCODE", pool=4, query="", gpu_ts=True)
    runs["B"] = _run("B", amf_mode="BYPASS", pool=4, query="", gpu_ts=True)
    runs["C"] = _run("C", amf_mode="ENCODE", pool=4, query="DRAIN_READY", gpu_ts=True)
    runs["D"] = _run("D", amf_mode="ENCODE", pool=6, query="DRAIN_READY", gpu_ts=False)
    runs["E"] = _run("E", amf_mode="ENCODE", pool=8, query="DRAIN_READY", gpu_ts=False)
    report = {"runs": runs, "order": ["A", "B", "C", "D", "E"]}
    if all(runs[t]["valid"] for t in ("A", "B", "C", "D", "E")):
        a = runs["A"]["true_fps"]
        b = runs["B"]["true_fps"]
        c = runs["C"]["true_fps"]
        d = runs["D"]["true_fps"]
        e = runs["E"]["true_fps"]
        print("\n=== ETAP 5U summary (FPS) ===", flush=True)
        print(f"  A ENCODE/pool4/REF  : {a:.2f}", flush=True)
        print(f"  B BYPASS/pool4      : {b:.2f}  (frontend ceiling)", flush=True)
        print(f"  C ENCODE/pool4/DRAIN: {c:.2f}", flush=True)
        print(f"  D ENCODE/pool6/DRAIN: {d:.2f}", flush=True)
        print(f"  E ENCODE/pool8/DRAIN: {e:.2f}", flush=True)
        print(f"  VCN gap (B-A)       : {b - a:.2f} FPS ({100*(b-a)/b:.1f}% of ceiling)", flush=True)
        print(f"  DRAIN_READY delta   : {c - a:+.2f} FPS", flush=True)
        print(f"  pool 6 delta vs A   : {d - a:+.2f} FPS", flush=True)
        print(f"  pool 8 delta vs A   : {e - a:+.2f} FPS", flush=True)
    (OUT / "etap5u_runs.json").write_text(json.dumps(report, indent=2, default=str),
                                          encoding="utf-8")
    print(f"\nJSON: {OUT / 'etap5u_runs.json'}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
