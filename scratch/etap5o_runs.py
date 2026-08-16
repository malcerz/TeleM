"""ETAP 5O — production AMF diagnostics runs.

Runs A/B/C/D (full production, AMD_AMF_DIAG=1) + E (SUBMIT_NO_MUX) and reports
per-run: TRUE FPS, wall, AMF queue (avg/med/p95/p99/max/trend), output cadence,
final drain.  Measurement only; encoder settings untouched.
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


def _env(amf_mode: str = "ENCODE", diag: bool = True) -> dict:
    env = dict(os.environ)
    for flag in ("AMD_GAUGE_AB_READBACK", "AMD_MAP_AB_READBACK", "AMD_CHART_AB_READBACK",
                 "AMD_CHART_STATIC_READBACK", "AMD_NATIVE_DIAGNOSTICS", "AMD_NATIVE_PROFILING",
                 "AMD_OVERLAY_PROFILE", "AMD_MAP_STATS", "AMD_TELEMETRY_MODE"):
        env.pop(flag, None)
    env["AMD_MAP_PATH"] = "GPU"
    env["AMD_MAP_FILTER"] = "LANCZOS"
    env["AMD_AMF_MODE"] = amf_mode
    env["AMD_AMF_DIAG"] = "1" if diag else "0"
    return env


def _run(tag: str, amf_mode: str) -> dict:
    mp4 = OUT / f"l5o_{tag}.mp4"
    t0 = time.time()
    proc = subprocess.run(
        [PY, str(RUNNER), "--frames", "1131", "--chart-path", "GPU_SPLIT",
         "--gauge-path", "GPU", "--output", str(mp4)],
        cwd=str(ROOT), env=_env(amf_mode), capture_output=True, text=True,
    )
    wall = time.time() - t0
    profile = mp4.with_suffix(mp4.suffix + ".amd_profile.json")
    if proc.returncode != 0 or not profile.exists():
        tail = "\n".join(proc.stdout.splitlines()[-20:])
        print(f"[{tag}] {amf_mode} rc={proc.returncode} wall={wall:.2f}s FAIL\n{tail}", flush=True)
        return {"tag": tag, "mode": amf_mode, "wall": wall, "valid": False}
    d = json.loads(profile.read_text(encoding="utf-8"))
    e5o = d.get("etap5o", {})
    fa = d["frame_accounting"]
    rec = {
        "tag": tag, "mode": amf_mode, "wall": wall,
        "true_fps": d.get("true_fps", 0.0),
        "valid": (fa.get("cadence_gpu") == 1131 and fa.get("hr_gpu") == 1131
                  and fa.get("map_gpu") == 1131
                  and d.get("etap5l", {}).get("gauge_gpu_frames") == 1131
                  and d.get("amf", {}).get("dropped_submissions") == 0),
        "queue": e5o.get("queue"),
        "cadence": e5o.get("cadence"),
        "outstanding_at_final_submit": e5o.get("outstanding_at_final_submit"),
        "drain_ms": e5o.get("drain_ms"),
        "frames_drained_in_flush": e5o.get("frames_drained_in_flush"),
        "input_full_total": e5o.get("input_full_total"),
        "submitted": e5o.get("submitted_total"),
        "output": e5o.get("output_total"),
    }
    q = rec["queue"]; c = rec["cadence"]
    print(f"[{tag}] {amf_mode:13s} wall={wall:.2f}s FPS={rec['true_fps']:.2f} "
          f"queue={q and (q['median'], q['max'], q['trend'])} "
          f"cadence={c and round(c['equivalent_fps'],1)}FPS "
          f"final_outstanding={rec['outstanding_at_final_submit']} "
          f"drain={rec['drain_ms']:.0f}ms({rec['frames_drained_in_flush']}) "
          f"input_full={rec['input_full_total']} valid={rec['valid']}", flush=True)
    return rec


def main() -> int:
    runs = {
        "A": _run("A", "ENCODE"),
        "B": _run("B", "ENCODE"),
        "C": _run("C", "ENCODE"),
        "D": _run("D", "ENCODE"),
        "E": _run("E", "SUBMIT_NO_MUX"),
    }
    report = {"runs": runs}
    enc = [runs[k] for k in ("A", "B", "C", "D") if runs[k]["valid"]]
    if enc:
        fps = [r["true_fps"] for r in enc]
        walls = [r["wall"] for r in enc]
        report["aggregate"] = {
            "median_fps": statistics.median(fps),
            "min_fps": min(fps), "max_fps": max(fps),
            "median_wall": statistics.median(walls),
            "realtime_factor": statistics.median(fps) / SOURCE_FPS,
        }
    (OUT / "etap5o_runs.json").write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print("\n=== ETAP 5O RUNS ===", flush=True)
    for k in ("A", "B", "C", "D", "E"):
        r = runs[k]
        print(f"  {k} {r['mode']:13s} wall={r['wall']:.2f}s FPS={r['true_fps']:.2f} "
              f"valid={r['valid']}", flush=True)
    if report.get("aggregate"):
        a = report["aggregate"]
        print(f"  ENCODE median FPS: {a['median_fps']:.2f}  "
              f"min {a['min_fps']:.2f} max {a['max_fps']:.2f}  "
              f"wall {a['median_wall']:.2f}s", flush=True)
        print(f"  realtime factor (median): {a['realtime_factor']:.3f}x", flush=True)
    if runs["E"].get("valid"):
        print(f"  SUBMIT_NO_MUX FPS: {runs['E']['true_fps']:.2f} "
              f"(vs encode+mux median {report.get('aggregate',{}).get('median_fps',0):.2f})",
              flush=True)
    print(f"  JSON: {OUT / 'etap5o_runs.json'}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
