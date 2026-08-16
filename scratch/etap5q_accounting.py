"""ETAP 5Q — accounting runs E/F (spec section 18/19).

E = REFERENCE + FRAME_ACCOUNTING, F = OPTIMIZED + FRAME_ACCOUNTING.
Compares compose med, process_frame med, frame_total med and computes how much
of the compose saving is absorbed by process_frame pacing.
"""
from __future__ import annotations

import json
import os
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
    env["AMD_FRAME_ACCOUNTING"] = "1"
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
        print(f"[{tag}] compose={compose_mode} rc={proc.returncode} wall={wall:.2f}s "
              f"FAIL\n{tail}", flush=True)
        return {"tag": tag, "compose": compose_mode, "wall": wall, "valid": False}
    d = json.loads(profile.read_text(encoding="utf-8"))
    fa = d.get("frame_accounting", {})
    e5p = d.get("etap5p", {}) or {}
    stages = e5p.get("stages", {}) or {}
    ft = e5p.get("frame_total_ms", {}) or {}

    def med(stage_name):
        s = stages.get(stage_name)
        if not s:
            return None
        if isinstance(s, dict):
            return s.get("median_ms", s.get("median"))
        return s

    ft = e5p.get("frame_total_ms", {}) or {}
    rec = {
        "tag": tag, "compose": compose_mode, "wall": wall,
        "true_fps": d.get("true_fps", 0.0),
        "compose_med": med("compose"),
        "process_frame_med": med("process_frame"),
        "frame_total_med": ft.get("median"),
        "stages": {k: (v.get("median_ms") if isinstance(v, dict) else v)
                   for k, v in stages.items()},
        "valid": (fa.get("cadence_gpu") == 1131 and fa.get("hr_gpu") == 1131
                  and fa.get("map_gpu") == 1131),
    }
    print(f"[{tag}] compose={compose_mode} wall={wall:.2f}s FPS={rec['true_fps']:.2f} "
          f"compose={rec['compose_med']} process_frame={rec['process_frame_med']} "
          f"frame_total={rec['frame_total_med']} valid={rec['valid']}", flush=True)
    return rec


def main() -> int:
    E = _run("E", "REFERENCE")
    F = _run("F", "OPTIMIZED")
    report = {"runs": {"E": E, "F": F}}
    if E.get("valid") and F.get("valid"):
        c_ref, c_opt = E["compose_med"], F["compose_med"]
        p_ref, p_opt = E["process_frame_med"], F["process_frame_med"]
        t_ref, t_opt = E["frame_total_med"], F["frame_total_med"]
        if None not in (c_ref, c_opt, p_ref, p_opt, t_ref, t_opt):
            compose_saved = c_ref - c_opt
            process_frame_shift = p_opt - p_ref
            frame_saved = t_ref - t_opt
            absorbed = (process_frame_shift / compose_saved) * 100.0 if compose_saved else 0.0
            report["absorption"] = {
                "compose_REF_ms": c_ref, "compose_OPT_ms": c_opt,
                "compose_saved_ms": compose_saved,
                "process_frame_REF_ms": p_ref, "process_frame_OPT_ms": p_opt,
                "process_frame_shift_ms": process_frame_shift,
                "frame_total_REF_ms": t_ref, "frame_total_OPT_ms": t_opt,
                "frame_saved_ms": frame_saved,
                "absorption_pct": absorbed,
            }
            print(f"\nABSORPTION:", flush=True)
            print(f"  compose:  {c_ref:.3f} -> {c_opt:.3f} ms  (saved {compose_saved:.3f})", flush=True)
            print(f"  process_frame: {p_ref:.3f} -> {p_opt:.3f} ms (shift {process_frame_shift:+.3f})",
                  flush=True)
            print(f"  frame_total: {t_ref:.3f} -> {t_opt:.3f} ms (saved {frame_saved:+.3f})",
                  flush=True)
            print(f"  absorbed by pacing: {absorbed:.1f}%  (frame_saved {frame_saved:.3f} ms/frame)",
                  flush=True)
    (OUT / "etap5q_accounting.json").write_text(json.dumps(report, indent=2, default=str),
                                                encoding="utf-8")
    print(f"\nJSON: {OUT / 'etap5q_accounting.json'}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
