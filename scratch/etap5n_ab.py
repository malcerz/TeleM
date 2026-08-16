"""ETAP 5N — production A/B/C/D: REFERENCE / PRECOMPUTED / REFERENCE / PRECOMPUTED.

Same session, 1131 frames each, full production GPU pipeline, profiling OFF.
Reports per-run: total wall, render-loop wall, TRUE FPS, telemetry median,
cache build time (PRE).  Aggregates REF median vs PRE median total wall + gain.
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


def _clean_env(mode: str) -> dict:
    env = dict(os.environ)
    for flag in ("AMD_GAUGE_AB_READBACK", "AMD_MAP_AB_READBACK", "AMD_CHART_AB_READBACK",
                 "AMD_CHART_STATIC_READBACK", "AMD_NATIVE_DIAGNOSTICS", "AMD_NATIVE_PROFILING",
                 "AMD_OVERLAY_PROFILE", "AMD_MAP_STATS"):
        env.pop(flag, None)
    env["AMD_MAP_PATH"] = "GPU"
    env["AMD_MAP_FILTER"] = "LANCZOS"
    env["AMD_TELEMETRY_MODE"] = mode
    return env


def _run(tag: str, mode: str) -> dict:
    mp4 = OUT / f"l5n_ab_{tag}.mp4"
    t0 = time.time()
    proc = subprocess.run(
        [PY, str(RUNNER), "--frames", "1131", "--chart-path", "GPU_SPLIT",
         "--gauge-path", "GPU", "--output", str(mp4)],
        cwd=str(ROOT), env=_clean_env(mode), capture_output=True, text=True,
    )
    wall = time.time() - t0
    profile = mp4.with_suffix(mp4.suffix + ".amd_profile.json")
    if proc.returncode != 0 or not profile.exists():
        tail = "\n".join(proc.stdout.splitlines()[-20:])
        print(f"[{tag}] {mode} rc={proc.returncode} wall={wall:.2f}s INVALID\n{tail}", flush=True)
        return {"tag": tag, "mode": mode, "wall": wall, "valid": False, "true_fps": 0.0}
    data = json.loads(profile.read_text(encoding="utf-8"))
    fa = data["frame_accounting"]
    e5n = data.get("etap5n", {})
    t = data.get("timings", {})
    cache = e5n.get("precomputed") or {}
    build_ms = cache.get("build_ms", 0.0)
    render_wall = max(0.0, wall - build_ms / 1000.0)
    render_fps = 1131.0 / render_wall if render_wall > 0 else 0.0
    valid = (
        data.get("diagnostics_enabled") is False and data.get("profiling_enabled") is False
        and fa.get("cadence_gpu") == 1131 and fa.get("hr_gpu") == 1131
        and fa.get("map_gpu") == 1131 and data.get("etap5l", {}).get("gauge_gpu_frames") == 1131
        and fa.get("amf_output") == 1131 and fa.get("muxed_frames") == 1131
        and data.get("amf", {}).get("dropped_submissions") == 0
    )
    rec = {
        "tag": tag, "mode": mode, "wall": wall, "render_wall": render_wall,
        "true_fps": data.get("true_fps", 0.0), "render_fps": render_fps,
        "telemetry_med_ms": t.get("Telemetry/frame_data", {}).get("median_ms", 0.0),
        "compose_med_ms": t.get("compose_overlay", {}).get("median_ms", 0.0),
        "cache_build_ms": build_ms, "drops": data.get("amf", {}).get("dropped_submissions"),
        "valid": valid,
    }
    print(f"[{tag}] {mode:11s} wall={wall:.3f}s render_wall={render_wall:.3f}s "
          f"FPS={rec['true_fps']:.3f} (render {render_fps:.3f}) "
          f"telemetry={rec['telemetry_med_ms']:.4f}ms build={build_ms:.0f}ms "
          f"valid={valid}", flush=True)
    return rec


def main() -> int:
    runs = {
        "A": _run("A", "REFERENCE"),
        "B": _run("B", "PRECOMPUTED"),
        "C": _run("C", "REFERENCE"),
        "D": _run("D", "PRECOMPUTED"),
    }
    refs = [runs[k] for k in ("A", "C") if runs[k]["valid"]]
    pres = [runs[k] for k in ("B", "D") if runs[k]["valid"]]
    report = {"runs": runs}
    if refs and pres:
        ref_walls = [r["wall"] for r in refs]
        pre_walls = [r["wall"] for r in pres]
        ref_med = statistics.median(ref_walls)
        pre_med = statistics.median(pre_walls)
        gain = (ref_med - pre_med) / ref_med * 100.0
        pre_render_med = statistics.median(r["render_wall"] for r in pres)
        pre_total_fps = 1131.0 / pre_med
        report.update({
            "ref_median_total_wall": ref_med,
            "pre_median_total_wall": pre_med,
            "total_gain_pct": gain,
            "pre_median_render_wall": pre_render_med,
            "pre_render_loop_fps": 1131.0 / pre_render_med,
            "ref_median_fps": statistics.median(r["true_fps"] for r in refs),
            "pre_median_fps": statistics.median(r["true_fps"] for r in pres),
            "realtime_factor": (1131.0 / pre_med) / SOURCE_FPS,
            "realtime_margin_pct": ((1131.0 / pre_med) - SOURCE_FPS) / SOURCE_FPS * 100.0,
        })
    (OUT / "etap5n_ab.json").write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print("\n=== ETAP 5N A/B/C/D ===", flush=True)
    for k in ("A", "B", "C", "D"):
        r = runs[k]
        print(f"  {k} {r['mode']:11s} wall={r['wall']:.3f}s FPS={r['true_fps']:.3f} "
              f"valid={r['valid']}", flush=True)
    if refs and pres:
        print(f"  REF median total wall: {ref_med:.3f} s", flush=True)
        print(f"  PRE median total wall: {pre_med:.3f} s", flush=True)
        print(f"  TOTAL GAIN: {gain:.2f} %", flush=True)
        print(f"  PRE render-loop FPS: {report['pre_render_loop_fps']:.3f} "
              f"(median render wall {pre_render_med:.3f} s)", flush=True)
        print(f"  REF median FPS: {report['ref_median_fps']:.3f} "
              f"PRE median FPS (incl build): {report['pre_median_fps']:.3f}", flush=True)
        print(f"  REALTIME (PRE total): {report['realtime_factor']:.3f}x "
              f"margin {report['realtime_margin_pct']:.2f} %", flush=True)
    print(f"  JSON: {OUT / 'etap5n_ab.json'}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
