"""ETAP 5N — full 1131 output regression: REFERENCE vs PRECOMPUTED telemetry.

Runs two full production exports (REF / PRECOMPUTED) on the full GPU pipeline,
compares framemd5 of the final MP4s, and reports frame accounting + telemetry
timing + cache stats + wall from both profiles.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

PY = r"c:/_DEV/TeleM/.venv-1/Scripts/python.exe"
RUNNER = ROOT / "scratch" / "run_etap5g_export.py"
OUT = ROOT / "Raporty" / "AMD_ETAP5G"
FFMPEG = r"C:\tools\ffmpeg.exe"


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


def _framemd5(mp4) -> str:
    proc = subprocess.run(
        [FFMPEG, "-v", "error", "-i", str(mp4), "-map", "0:v", "-f", "framemd5", "-"],
        capture_output=True, text=True,
    )
    return hashlib.sha256(proc.stdout.encode()).hexdigest()


def _run(tag: str, mode: str) -> dict:
    mp4 = OUT / f"l5n_full_{tag}.mp4"
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
        print(f"[{tag}] rc={proc.returncode} wall={wall:.2f}s FAIL\n{tail}", flush=True)
        return {"tag": tag, "rc": proc.returncode, "wall": wall}
    data = json.loads(profile.read_text(encoding="utf-8"))
    fa = data["frame_accounting"]
    e5n = data.get("etap5n", {})
    t = data.get("timings", {})
    rec = {
        "tag": tag, "mode": mode, "wall": wall,
        "true_fps": data.get("true_fps", 0.0),
        "telemetry_med_ms": t.get("Telemetry/frame_data", {}).get("median_ms", 0.0),
        "compose_med_ms": t.get("compose_overlay", {}).get("median_ms", 0.0),
        "cadence": fa.get("cadence_gpu"), "hr": fa.get("hr_gpu"),
        "map": fa.get("map_gpu"), "gauge": data.get("etap5l", {}).get("gauge_gpu_frames"),
        "amf_sub": fa.get("amf_submitted"), "amf_out": fa.get("amf_output"),
        "muxed": fa.get("muxed_frames"), "drops": data.get("amf", {}).get("dropped_submissions"),
        "cache": e5n.get("precomputed"),
    }
    print(f"[{tag}] {mode} wall={wall:.3f}s FPS={rec['true_fps']:.3f} "
          f"telemetry={rec['telemetry_med_ms']:.4f}ms drops={rec['drops']}", flush=True)
    return rec


def main() -> int:
    ref = _run("ref", "REFERENCE")
    pre = _run("pre", "PRECOMPUTED")
    h_ref = _framemd5(OUT / "l5n_full_ref.mp4")
    h_pre = _framemd5(OUT / "l5n_full_pre.mp4")
    identical = h_ref == h_pre
    print(f"\nframemd5 REF: {h_ref}", flush=True)
    print(f"framemd5 PRE: {h_pre}", flush=True)
    print(f"identical: {'YES' if identical else 'NO'}", flush=True)

    result = {
        "status": "PASS" if identical and ref["drops"] == 0 and pre["drops"] == 0 else "FAIL",
        "identical": identical,
        "ref": ref, "pre": pre,
    }
    (OUT / "etap5n_output_regression.json").write_text(
        json.dumps(result, indent=2, default=str), encoding="utf-8")
    print(f"\nOUTPUT REGRESSION: {result['status']}", flush=True)
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
