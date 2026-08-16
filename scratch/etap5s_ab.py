"""ETAP 5S — production A/B/C/D (spec section 17).

A=REFERENCE, B=STATIC_CACHE, C=REFERENCE, D=STATIC_CACHE — 1131 frames each,
accounting OFF (native + Python), profiling OFF.  AMD_COMPOSE_5Q=OPTIMIZED.
Reports TRUE FPS and wall.
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


def _env(vp_mode: str) -> dict:
    env = dict(os.environ)
    for flag in ("AMD_GAUGE_AB_READBACK", "AMD_MAP_AB_READBACK", "AMD_CHART_AB_READBACK",
                 "AMD_CHART_STATIC_READBACK", "AMD_NATIVE_DIAGNOSTICS", "AMD_NATIVE_PROFILING",
                 "AMD_OVERLAY_PROFILE", "AMD_MAP_STATS", "AMD_TELEMETRY_MODE",
                 "AMD_FRAME_ACCOUNTING", "AMD_AMF_DIAG", "AMD_COMPOSE_5Q",
                 "AMD_NATIVE_FRAME_ACCOUNTING", "AMD_VP_STATE_MODE"):
        env.pop(flag, None)
    env["AMD_MAP_PATH"] = "GPU"
    env["AMD_MAP_FILTER"] = "LANCZOS"
    env["AMD_COMPOSE_5Q"] = "OPTIMIZED"
    env["AMD_VP_STATE_MODE"] = vp_mode
    return env


def _run(tag: str, vp_mode: str) -> dict:
    mp4 = OUT / f"l5s_{tag}.mp4"
    t0 = time.time()
    proc = subprocess.run(
        [PY, str(RUNNER), "--frames", "1131", "--chart-path", "GPU_SPLIT",
         "--gauge-path", "GPU", "--output", str(mp4)],
        cwd=str(ROOT), env=_env(vp_mode), capture_output=True, text=True,
    )
    wall = time.time() - t0
    profile = mp4.with_suffix(mp4.suffix + ".amd_profile.json")
    if proc.returncode != 0 or not profile.exists():
        tail = "\n".join(proc.stdout.splitlines()[-15:])
        print(f"[{tag}] {vp_mode} rc={proc.returncode} wall={wall:.2f}s FAIL\n{tail}", flush=True)
        return {"tag": tag, "vp_mode": vp_mode, "wall": wall, "valid": False}
    d = json.loads(profile.read_text(encoding="utf-8"))
    fa = d.get("frame_accounting", {})
    e5l = d.get("etap5l", {})
    amf = d.get("amf", {})
    rec = {
        "tag": tag, "vp_mode": vp_mode, "wall": wall,
        "true_fps": d.get("true_fps", 0.0),
        "valid": (fa.get("cadence_gpu") == 1131 and fa.get("hr_gpu") == 1131
                  and fa.get("map_gpu") == 1131
                  and e5l.get("gauge_gpu_frames") == 1131
                  and amf.get("dropped_submissions") == 0),
    }
    print(f"[{tag}] {vp_mode:12s} wall={wall:.2f}s FPS={rec['true_fps']:.2f} "
          f"valid={rec['valid']}", flush=True)
    return rec


def main() -> int:
    runs = {}
    for tag, mode in (("A", "REFERENCE"), ("B", "STATIC_CACHE"),
                      ("C", "REFERENCE"), ("D", "STATIC_CACHE")):
        runs[tag] = _run(tag, mode)
    report = {"runs": runs, "order": ["A", "B", "C", "D"]}
    if all(runs[t]["valid"] for t in ("A", "B", "C", "D")):
        ref = [runs[t]["true_fps"] for t in ("A", "C")]
        cache = [runs[t]["true_fps"] for t in ("B", "D")]
        ref_w = [runs[t]["wall"] for t in ("A", "C")]
        cache_w = [runs[t]["wall"] for t in ("B", "D")]
        report["ref_fps"] = ref
        report["cache_fps"] = cache
        report["ref_fps_med"] = statistics.median(ref)
        report["cache_fps_med"] = statistics.median(cache)
        report["fps_delta"] = statistics.median(cache) - statistics.median(ref)
        report["ref_wall_med"] = statistics.median(ref_w)
        report["cache_wall_med"] = statistics.median(cache_w)
        print(f"\nREFERENCE FPS: {ref} med={report['ref_fps_med']:.3f}", flush=True)
        print(f"STATIC_CACHE FPS: {cache} med={report['cache_fps_med']:.3f}", flush=True)
        print(f"FPS delta: {report['fps_delta']:+.3f}", flush=True)
        print(f"Wall REF med={report['ref_wall_med']:.2f}s "
              f"CACHE med={report['cache_wall_med']:.2f}s", flush=True)
    (OUT / "etap5s_ab.json").write_text(json.dumps(report, indent=2, default=str),
                                        encoding="utf-8")
    print(f"\nJSON: {OUT / 'etap5s_ab.json'}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
