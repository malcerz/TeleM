"""ETAP 5L — full production A/B/C/D benchmark (gauge).

Runs 4 full 1131-frame exports (GPU_SPLIT charts + GPU map in all):
  A: CPU_REFERENCE gauge    C: CPU_REFERENCE gauge
  B: GPU gauge              D: GPU gauge
profiling OFF, diagnostics OFF, readback OFF.

Collects per-run TRUE FPS and per-stage timing medians, then reports the
A/B/C/D table, medians and gain %.
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
    ("A", "CPU_REFERENCE", "l5_full_A_cpu.mp4"),
    ("B", "GPU", "l5_full_B_gpu.mp4"),
    ("C", "CPU_REFERENCE", "l5_full_C_cpu.mp4"),
    ("D", "GPU", "l5_full_D_gpu.mp4"),
]

FPS_KEYS = [
    "compose_overlay", "gauge_tobytes", "gauge_upload",
    "GPU gauge blend submit", "chart_cpu_tobytes", "chart_python_upload",
    "chart_dynamic_tobytes", "chart_dynamic_upload", "GPU chart blend submit",
    "HUD dirty extract", "PIL/buffer preparation", "update_hud",
    "Telemetry/frame_data", "map_cpu_upload",
]


def median(vals):
    if not vals:
        return 0.0
    s = sorted(vals)
    n = len(s)
    if n % 2 == 1:
        return s[n // 2]
    return (s[n // 2 - 1] + s[n // 2]) / 2.0


def run_one(label, gauge_path, output):
    out = OUT_DIR / output
    log = OUT_DIR / (output + ".log")
    print(f"\n===== RUN {label}: gauge {gauge_path} -> {out.name} =====", flush=True)
    started = time.time()
    rc = -1
    proc_out = ""
    for attempt in (1, 2):
        if attempt > 1:
            time.sleep(5.0)
        proc = subprocess.run(
            [PY, str(RUNNER), "--frames", "1131", "--chart-path", "GPU_SPLIT",
             "--gauge-path", gauge_path, "--output", str(out)],
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
    print("\n".join(proc_out.splitlines()[-8:]), flush=True)
    profile = out.with_suffix(out.suffix + ".amd_profile.json")
    data = {}
    if profile.exists():
        data = json.loads(profile.read_text(encoding="utf-8"))
    data["_run_elapsed_s"] = elapsed
    data["_rc"] = rc
    return data


def report(results):
    print("\n\n===== ETAP 5L FULL PRODUCTION A/B/C/D SUMMARY =====")
    print(f"{'Run':<4}{'gauge':<14}{'TRUE FPS':>10}{'wall s':>9}{'enc':>6}{'mux':>6}{'rc':>4}")
    for label, gp, _ in RUNS:
        d = results[label]
        print(f"{label:<4}{gp:<14}{d.get('true_fps', 0):>10.3f}"
              f"{d.get('_run_elapsed_s', 0):>9.1f}"
              f"{d.get('encoded_frames', 0):>6}{d.get('muxed_frames', 0):>6}"
              f"{d.get('_rc', -1):>4}", flush=True)
    print("\nPer-stage median (ms):")
    for key in FPS_KEYS:
        row = []
        for label, _, _ in RUNS:
            t = results[label].get("timings", {}).get(key)
            row.append(t.get("median_ms", 0.0) if t else 0.0)
        print(f"  {key:<28}" + "".join(f"{v:>10.3f}" for v in row))
    cpu = [results[l]["true_fps"] for l in ("A", "C")]
    gpu = [results[l]["true_fps"] for l in ("B", "D")]
    cpu_med = median(cpu)
    gpu_med = median(gpu)
    gain = (gpu_med - cpu_med) / cpu_med * 100.0 if cpu_med else 0.0
    print(f"\nCPU runs:      {cpu}")
    print(f"GPU runs:      {gpu}")
    print(f"CPU_REFERENCE median: {cpu_med:.3f} FPS")
    print(f"GPU gauge median:     {gpu_med:.3f} FPS")
    print(f"GAIN:                 {gain:+.2f} %")
    return 0


def main() -> int:
    if "--report-only" in sys.argv:
        results = json.loads((OUT_DIR / "l5_full_ab_production.json").read_text(encoding="utf-8"))
        return report(results)
    results = {}
    for label, gp, output in RUNS:
        results[label] = run_one(label, gp, output)
    out = OUT_DIR / "l5_full_ab_production.json"
    out.write_text(json.dumps(results, indent=2, default=str), encoding="utf-8")
    print(f"\nFull JSON: {out}")
    return report(results)


if __name__ == "__main__":
    raise SystemExit(main())
