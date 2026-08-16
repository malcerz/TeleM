"""ETAP 5W — 5Q final decision tests (spec 21/22/23).

Correctness: pool8+REF vs pool8+OPT (1131, framemd5 identical, drops=0).
Performance: A=REF, B=OPT, C=REF, D=OPT (1131, profiling OFF, readbacks OFF).
Reports median gain and framemd5 equality -> input for the 5Q default decision.
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
FF = r"C:\tools\ffmpeg.exe"


def _env(compose: str) -> dict:
    env = dict(os.environ)
    for flag in ("AMD_GAUGE_AB_READBACK", "AMD_MAP_AB_READBACK", "AMD_CHART_AB_READBACK",
                 "AMD_CHART_STATIC_READBACK", "AMD_NATIVE_DIAGNOSTICS", "AMD_NATIVE_PROFILING",
                 "AMD_OVERLAY_PROFILE", "AMD_MAP_STATS", "AMD_TELEMETRY_MODE",
                 "AMD_FRAME_ACCOUNTING", "AMD_AMF_DIAG", "AMD_COMPOSE_5Q",
                 "AMD_NATIVE_FRAME_ACCOUNTING", "AMD_VP_STATE_MODE",
                 "AMD_GPU_TIMESTAMP_PROFILE", "AMD_AMF_MODE", "AMD_AMF_QUERY_MODE",
                 "AMD_VP_POOL_SIZE", "AMD_POOL_LIFECYCLE_STATS", "AMD_CHART_PATH",
                 "AMD_GAUGE_PATH"):
        env.pop(flag, None)
    env["AMD_MAP_PATH"] = "GPU"
    env["AMD_MAP_FILTER"] = "LANCZOS"
    env["AMD_VP_STATE_MODE"] = "REFERENCE"
    env["AMD_VP_POOL_SIZE"] = "8"
    env["AMD_COMPOSE_5Q"] = compose
    return env


def _run(tag: str, compose: str) -> dict:
    mp4 = OUT / f"l5w_{tag}.mp4"
    t0 = time.time()
    proc = subprocess.run(
        [PY, str(RUNNER), "--frames", "1131", "--chart-path", "GPU_SPLIT",
         "--gauge-path", "GPU", "--output", str(mp4)],
        cwd=str(ROOT), env=_env(compose), capture_output=True, text=True,
    )
    wall = time.time() - t0
    profile = mp4.with_suffix(mp4.suffix + ".amd_profile.json")
    if proc.returncode != 0 or not profile.exists():
        print(f"[{tag}] FAIL rc={proc.returncode} wall={wall:.2f}s\n"
              f"{proc.stdout.splitlines()[-8:]}", flush=True)
        return {"tag": tag, "compose": compose, "wall": wall, "valid": False}
    d = json.loads(profile.read_text(encoding="utf-8"))
    fa = d.get("frame_accounting", {})
    amf = d.get("amf", {})
    rec = {
        "tag": tag, "compose": compose, "wall": wall, "true_fps": d.get("true_fps", 0.0),
        "muxed": fa.get("muxed_frames", 0), "dropped": amf.get("dropped_submissions", -1),
        "valid": (fa.get("muxed_frames") == 1131 and amf.get("dropped_submissions") == 0),
    }
    print(f"[{tag}] {compose} wall={wall:.2f}s FPS={rec['true_fps']:.2f} "
          f"muxed={rec['muxed']} dropped={rec['dropped']} valid={rec['valid']}", flush=True)
    return rec


def _hashes(tag: str) -> list:
    md5f = OUT / f"l5w_{tag}.md5"
    subprocess.run([FF, "-y", "-hide_banner", "-loglevel", "error", "-i",
                    str(OUT / f"l5w_{tag}.mp4"), "-map", "0:v:0", "-f", "framemd5",
                    str(md5f)], check=True)
    return [l.split()[-1] for l in md5f.read_text(encoding="utf-8").splitlines()
            if l and l[0].isdigit()]


def main() -> int:
    runs = {}
    for tag, compose in [("R1", "REFERENCE"), ("O1", "OPTIMIZED"),
                         ("R2", "REFERENCE"), ("O2", "OPTIMIZED")]:
        runs[tag] = _run(tag, compose)
    report = {"runs": runs}
    if all(runs[t]["valid"] for t in runs):
        ref = statistics.median([runs["R1"]["true_fps"], runs["R2"]["true_fps"]])
        opt = statistics.median([runs["O1"]["true_fps"], runs["O2"]["true_fps"]])
        report["ref_fps_median"] = ref
        report["opt_fps_median"] = opt
        report["gain"] = opt - ref
        report["gain_pct"] = (opt - ref) / ref * 100.0
        # correctness: framemd5 R1 vs O1
        hr, ho = _hashes("R1"), _hashes("O1")
        same = sum(1 for a, b in zip(hr, ho) if a == b)
        report["framemd5"] = {"identical": same, "total": len(ho),
                              "pass": same == len(hr) == len(ho)}
        print("\n=== 5W 5Q final ===", flush=True)
        print(f"  REF med {ref:.2f} FPS (R1={runs['R1']['true_fps']:.2f} R2={runs['R2']['true_fps']:.2f})", flush=True)
        print(f"  OPT med {opt:.2f} FPS (O1={runs['O1']['true_fps']:.2f} O2={runs['O2']['true_fps']:.2f})", flush=True)
        print(f"  gain {opt-ref:+.2f} FPS ({report['gain_pct']:+.1f}%)", flush=True)
        print(f"  framemd5 REF vs OPT: {same}/{len(ho)} identical pass={report['framemd5']['pass']}", flush=True)
    (OUT / "etap5w_5q.json").write_text(json.dumps(report, indent=2, default=str),
                                        encoding="utf-8")
    return 0 if report.get("framemd5", {}).get("pass", False) else 1


if __name__ == "__main__":
    raise SystemExit(main())
