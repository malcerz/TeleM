"""ETAP 5K — full production A/B/C/D benchmark (section 28).

Runs 4 full 1131-frame exports in the same session:
  A: GPU charts (5J)      C: GPU charts (5J)
  B: GPU_SPLIT (5K)       D: GPU_SPLIT (5K)
profiling OFF, diagnostics OFF, readback OFF (the exporter's production mode).

Collects per-run TRUE FPS from the .amd_profile.json and the per-stage timing
summaries, then reports the A/B/C/D table, medians and gain %.
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PY = r"c:\_DEV\TeleM\.venv-1\Scripts\python.exe"
RUNNER = ROOT / "scratch" / "run_etap5g_export.py"
OUT_DIR = ROOT / "Raporty" / "AMD_ETAP5G"
OUT_DIR.mkdir(parents=True, exist_ok=True)

RUNS = [
    ("A", "GPU", "k5_full_A_gpu.mp4"),
    ("B", "GPU_SPLIT", "k5_full_B_split.mp4"),
    ("C", "GPU", "k5_full_C_gpu.mp4"),
    ("D", "GPU_SPLIT", "k5_full_D_split.mp4"),
]

FPS_KEYS = [
    "compose_overlay", "chart_cpu_tobytes", "chart_python_upload",
    "GPU chart blend submit", "HUD dirty extract", "PIL/buffer preparation",
    "update_hud", "Telemetry/frame_data",
]


def run_one(label: str, path: str, output: str) -> dict:
    out = OUT_DIR / output
    log = OUT_DIR / (output + ".log")
    print(f"\n===== RUN {label}: {path} -> {out.name} =====", flush=True)
    started = time.time()
    rc = -1
    proc_out = ""
    # AMF/D3D11 on this APU needs the previous context fully torn down before
    # a new one can be created (rapid back-to-back inits can fail transiently).
    # Retry once after a short settle delay.
    for attempt in (1, 2):
        if attempt > 1:
            time.sleep(5.0)
        proc = subprocess.run(
            [PY, str(RUNNER), "--frames", "1131", "--chart-path", path,
             "--output", str(out)],
            cwd=str(ROOT), capture_output=True, text=True,
        )
        proc_out = proc.stdout + proc.stderr
        rc = proc.returncode
        if rc == 0:
            break
        print(f"  [WARN] run {label} attempt {attempt} rc={rc}, retrying...", flush=True)
        time.sleep(3.0)
    log.write_text(proc_out, encoding="utf-8")
    elapsed = time.time() - started
    tail = "\n".join(proc_out.splitlines()[-8:])
    print(tail, flush=True)
    profile = out.with_suffix(out.suffix + ".amd_profile.json")
    data = {}
    if profile.exists():
        data = json.loads(profile.read_text(encoding="utf-8"))
    else:
        print(f"  [WARN] profile missing for {label}: {profile}", flush=True)
    data["_run_elapsed_s"] = elapsed
    data["_rc"] = rc
    return data


def median(vals):
    if not vals:
        return 0.0
    s = sorted(vals)
    n = len(s)
    if n % 2 == 1:
        return s[n // 2]
    return (s[n // 2 - 1] + s[n // 2]) / 2.0


def main() -> int:
    if "--report-only" in sys.argv:
        results = json.loads((OUT_DIR / "k5_full_ab_production.json").read_text(encoding="utf-8"))
        return report(results)
    results: dict[str, dict] = {}
    for label, path, output in RUNS:
        results[label] = run_one(label, path, output)
    out = OUT_DIR / "k5_full_ab_production.json"
    out.write_text(json.dumps(results, indent=2, default=str), encoding="utf-8")
    print(f"\nFull JSON: {out}")
    return report(results)


def report(results: dict) -> int:
    print("\n\n===== ETAP 5K FULL PRODUCTION A/B/C/D SUMMARY =====")
    print(f"{'Run':<4}{'Path':<12}{'TRUE FPS':>10}{'wall s':>9}{'enc':>6}{'mux':>6}{'rc':>4}")
    for label, path, _ in RUNS:
        d = results[label]
        print(
            f"{label:<4}{path:<12}"
            f"{d.get('true_fps', 0.0):>10.3f}"
            f"{d.get('_run_elapsed_s', 0.0):>9.1f}"
            f"{d.get('encoded_frames', 0):>6}{d.get('muxed_frames', 0):>6}"
            f"{d.get('_rc', -1):>4}",
            flush=True,
        )

    print("\nPer-stage median (ms) A vs B vs C vs D:")
    for key in FPS_KEYS:
        row = []
        for label, path, _ in RUNS:
            t = results[label].get("timings", {}).get(key)
            row.append(t.get("median_ms", 0.0) if t else 0.0)
        print(f"  {key:<28}" + "".join(f"{v:>10.3f}" for v in row))

    gpu_fps = [results[l].get("true_fps", 0.0) for l in ("A", "C")]
    split_fps = [results[l].get("true_fps", 0.0) for l in ("B", "D")]
    gpu_med = median(gpu_fps)
    split_med = median(split_fps)
    gain = (split_med - gpu_med) / gpu_med * 100.0 if gpu_med else 0.0
    print(f"\nGPU runs:      {gpu_fps}")
    print(f"GPU_SPLIT runs:{split_fps}")
    print(f"GPU median FPS:    {gpu_med:.3f}")
    print(f"GPU_SPLIT median:  {split_med:.3f}")
    print(f"GAIN:              {gain:+.2f} %")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
