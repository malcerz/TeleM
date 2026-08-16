"""ETAP 5T — observer + GPU timeline runs (spec 13/16).

A: GPU-ts OFF, native acct OFF (control).
B: GPU-ts ON (observer 1).
C: GPU-ts ON (observer 2, reproduce).
D: GPU-ts ON + native acct ON (correlation CPU wait <-> GPU timeline).

All: AMD_VP_STATE_MODE=REFERENCE, AMD_COMPOSE_5Q=OPTIMIZED, telemetry REFERENCE.
Reports wall / TRUE FPS / observer overhead (<=5% required).
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


def _env(gpu_ts: bool, native_fa: bool) -> dict:
    env = dict(os.environ)
    for flag in ("AMD_GAUGE_AB_READBACK", "AMD_MAP_AB_READBACK", "AMD_CHART_AB_READBACK",
                 "AMD_CHART_STATIC_READBACK", "AMD_NATIVE_DIAGNOSTICS", "AMD_NATIVE_PROFILING",
                 "AMD_OVERLAY_PROFILE", "AMD_MAP_STATS", "AMD_TELEMETRY_MODE",
                 "AMD_FRAME_ACCOUNTING", "AMD_AMF_DIAG", "AMD_COMPOSE_5Q",
                 "AMD_NATIVE_FRAME_ACCOUNTING", "AMD_VP_STATE_MODE",
                 "AMD_GPU_TIMESTAMP_PROFILE"):
        env.pop(flag, None)
    env["AMD_MAP_PATH"] = "GPU"
    env["AMD_MAP_FILTER"] = "LANCZOS"
    env["AMD_COMPOSE_5Q"] = "OPTIMIZED"
    env["AMD_VP_STATE_MODE"] = "REFERENCE"
    if gpu_ts:
        env["AMD_GPU_TIMESTAMP_PROFILE"] = "1"
    if native_fa:
        env["AMD_NATIVE_FRAME_ACCOUNTING"] = "1"
    return env


def _run(tag: str, gpu_ts: bool, native_fa: bool) -> dict:
    mp4 = OUT / f"l5t_{tag}.mp4"
    t0 = time.time()
    proc = subprocess.run(
        [PY, str(RUNNER), "--frames", "1131", "--chart-path", "GPU_SPLIT",
         "--gauge-path", "GPU", "--output", str(mp4)],
        cwd=str(ROOT), env=_env(gpu_ts, native_fa), capture_output=True, text=True,
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
    rec = {
        "tag": tag, "gpu_ts": gpu_ts, "native_fa": native_fa,
        "wall": wall, "true_fps": d.get("true_fps", 0.0),
        "gpu_timeline_frames": gpu_frames,
        "valid": (fa.get("cadence_gpu") == 1131 and fa.get("hr_gpu") == 1131
                  and fa.get("map_gpu") == 1131
                  and e5l.get("gauge_gpu_frames") == 1131
                  and amf.get("dropped_submissions") == 0),
    }
    print(f"[{tag}] gpu_ts={gpu_ts} native_fa={native_fa} wall={wall:.2f}s "
          f"FPS={rec['true_fps']:.2f} gpu_tl={gpu_frames} valid={rec['valid']}", flush=True)
    return rec


def main() -> int:
    runs = {}
    runs["A"] = _run("A", gpu_ts=False, native_fa=False)
    runs["B"] = _run("B", gpu_ts=True, native_fa=False)
    runs["C"] = _run("C", gpu_ts=True, native_fa=False)
    runs["D"] = _run("D", gpu_ts=True, native_fa=True)
    report = {"runs": runs, "order": ["A", "B", "C", "D"]}
    if all(runs[t]["valid"] for t in ("A", "B", "C", "D")):
        a = runs["A"]["wall"]
        bc = statistics.median([runs["B"]["wall"], runs["C"]["wall"]])
        ovh = (bc - a) / a * 100.0
        report["observer_overhead_pct"] = ovh
        print(f"\nGPU-ts observer overhead (BC-A)/A: {ovh:.2f}%", flush=True)
        print(f"  A={runs['A']['true_fps']:.2f} FPS, B={runs['B']['true_fps']:.2f}, "
              f"C={runs['C']['true_fps']:.2f}, D={runs['D']['true_fps']:.2f}", flush=True)
    (OUT / "etap5t_observer.json").write_text(json.dumps(report, indent=2, default=str),
                                              encoding="utf-8")
    print(f"\nJSON: {OUT / 'etap5t_observer.json'}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
