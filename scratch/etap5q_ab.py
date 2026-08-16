"""ETAP 5Q — production A/B/C/D runs (spec section 17).

A=REFERENCE, B=OPTIMIZED, C=REFERENCE, D=OPTIMIZED — 1131 frames each,
accounting OFF.  Alternating order to counter thermal drift.  Reports TRUE FPS
and wall per run plus medians.
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


def _env(compose_mode: str) -> dict:
    env = dict(os.environ)
    for flag in ("AMD_GAUGE_AB_READBACK", "AMD_MAP_AB_READBACK", "AMD_CHART_AB_READBACK",
                 "AMD_CHART_STATIC_READBACK", "AMD_NATIVE_DIAGNOSTICS", "AMD_NATIVE_PROFILING",
                 "AMD_OVERLAY_PROFILE", "AMD_MAP_STATS", "AMD_TELEMETRY_MODE",
                 "AMD_FRAME_ACCOUNTING", "AMD_AMF_DIAG", "AMD_COMPOSE_5Q"):
        env.pop(flag, None)
    env["AMD_MAP_PATH"] = "GPU"
    env["AMD_MAP_FILTER"] = "LANCZOS"
    env["AMD_COMPOSE_5Q"] = compose_mode
    return env


def _run(tag: str, compose_mode: str) -> dict:
    mp4 = OUT / f"l5q_{tag}.mp4"
    t0 = time.time()
    proc = subprocess.run(
        [PY, str(RUNNER), "--frames", "1131", "--chart-path", "GPU_SPLIT",
         "--gauge-path", "GPU", "--output", str(mp4)],
        cwd=str(ROOT), env=_env(compose_mode),
        capture_output=True, text=True,
    )
    wall = time.time() - t0
    profile = mp4.with_suffix(mp4.suffix + ".amd_profile.json")
    if proc.returncode != 0 or not profile.exists():
        tail = "\n".join(proc.stdout.splitlines()[-20:])
        print(f"[{tag}] compose={compose_mode} rc={proc.returncode} "
              f"wall={wall:.2f}s FAIL\n{tail}", flush=True)
        return {"tag": tag, "compose": compose_mode, "wall": wall, "valid": False}
    d = json.loads(profile.read_text(encoding="utf-8"))
    fa = d.get("frame_accounting", {})
    e5l = d.get("etap5l", {})
    amf = d.get("amf", {})
    comp = (d.get("timings", {}) or {}).get("compose_overlay", {}) or {}
    rec = {
        "tag": tag, "compose": compose_mode, "wall": wall,
        "true_fps": d.get("true_fps", 0.0),
        "compose_overlay_med": float(comp.get("median_ms", 0.0) or 0.0),
        "valid": (fa.get("cadence_gpu") == 1131 and fa.get("hr_gpu") == 1131
                  and fa.get("map_gpu") == 1131
                  and e5l.get("gauge_gpu_frames") == 1131
                  and amf.get("dropped_submissions") == 0),
    }
    print(f"[{tag}] compose={compose_mode} wall={wall:.2f}s FPS={rec['true_fps']:.2f} "
          f"compose_med={rec['compose_overlay_med']:.3f} valid={rec['valid']}", flush=True)
    return rec


def main() -> int:
    runs = {}
    for tag, mode in (("A", "REFERENCE"), ("B", "OPTIMIZED"),
                      ("C", "REFERENCE"), ("D", "OPTIMIZED")):
        runs[tag] = _run(tag, mode)
    report = {"runs": runs, "order": ["A", "B", "C", "D"]}
    ref_fps = [runs[t]["true_fps"] for t in ("A", "C")]
    opt_fps = [runs[t]["true_fps"] for t in ("B", "D")]
    if all(runs[t]["valid"] for t in ("A", "B", "C", "D")):
        report["ref_fps"] = ref_fps
        report["opt_fps"] = opt_fps
        report["ref_fps_med"] = statistics.median(ref_fps)
        report["opt_fps_med"] = statistics.median(opt_fps)
        report["fps_delta"] = report["opt_fps_med"] - report["ref_fps_med"]
        report["fps_delta_pct"] = (report["fps_delta"] / report["ref_fps_med"]) * 100.0
        ref_wall = [runs[t]["wall"] for t in ("A", "C")]
        opt_wall = [runs[t]["wall"] for t in ("B", "D")]
        report["ref_wall_med"] = statistics.median(ref_wall)
        report["opt_wall_med"] = statistics.median(opt_wall)
        print(f"\nREFERENCE FPS: {ref_fps} med={report['ref_fps_med']:.3f}", flush=True)
        print(f"OPTIMIZED FPS: {opt_fps} med={report['opt_fps_med']:.3f}", flush=True)
        print(f"FPS delta: {report['fps_delta']:+.3f} ({report['fps_delta_pct']:+.2f}%)", flush=True)
        print(f"Wall REF med={report['ref_wall_med']:.2f}s  OPT med={report['opt_wall_med']:.2f}s",
              flush=True)
    else:
        print("\nSOME RUNS INVALID", flush=True)
    (OUT / "etap5q_ab.json").write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print(f"\nJSON: {OUT / 'etap5q_ab.json'}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
