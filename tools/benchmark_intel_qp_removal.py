"""Measure the existing GUI Intel harness without changing its rendering workload."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time

import psutil

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from run_intel_vbr_matrix import GpuCounter


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--name", required=True)
    parser.add_argument("--frames", type=int, default=1800)
    parser.add_argument("--qp-off", action="store_true")
    parser.add_argument("--native-dll", type=Path)
    args = parser.parse_args()
    if args.frames < 1800:
        parser.error("Performance comparisons require at least 1800 frames")
    out = ROOT / "Raporty/intel_qp_removal_20261019" / args.name
    out.mkdir(parents=True, exist_ok=False)
    layout = ROOT / "Raporty/intel_vbr_qp_20261017/layout.json"
    result = out / "harness.json"
    env = os.environ.copy()
    env.update(QT_QPA_PLATFORM="offscreen", APPDATA=str(ROOT / "scratch/qp-bench-profile"),
               LOCALAPPDATA=str(ROOT / "scratch/qp-bench-local"))
    for key in ("TELEM_INTEL_QUANT_TELEMETRY", "TELEM_INTEL_QP_TRACE", "TELEM_INTEL_TARGET_USAGE",
                "TELEM_PIPELINE_AUDIT", "TELEM_INTEL_FORCE_SERIAL_7D"):
        env.pop(key, None)
    if args.qp_off:
        env["TELEM_INTEL_QUANT_TELEMETRY"] = "0"
    native_dll = args.native_dll.resolve() if args.native_dll else ROOT / "runtime/intel/bin/telem_intel_native.dll"
    env["TELEM_INTEL_NATIVE_DLL"] = str(native_dll)
    cmd = [sys.executable, str(ROOT / "SportCamHUD.py"), "--test-intel-export",
           "--intel-path", "native", "--codec", "hevc", "--profile", "fast",
           "--frames", str(args.frames), "--bitrate", "40M", "--video", r"C:\GoPro\GX010378.MP4",
           "--fit", r"C:\GoPro\2026-10-15_15-03-50.fit", "--layout", str(layout),
           "--watchdog-seconds", "900", "--output", str(out / "output.mp4"), "--result-json", str(result)]
    samples = []
    counter = None
    counter_error = ""
    try:
        counter = GpuCounter()
    except Exception as exc:
        counter_error = str(exc)
    started = time.perf_counter()
    with (out / "export.log").open("w", encoding="utf-8") as log:
        proc = subprocess.Popen(cmd, cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT)
        known = {}
        while proc.poll() is None:
            if time.perf_counter() - started > 960:
                proc.kill()
                raise TimeoutError("Canonical harness exceeded watchdog allowance")
            try:
                processes = [psutil.Process(proc.pid)] + psutil.Process(proc.pid).children(recursive=True)
                cpu = 0.0
                for process in processes:
                    if process.pid not in known:
                        known[process.pid] = process
                    cpu += known[process.pid].cpu_percent()
                pids = {p.pid for p in processes}
                gpu = counter.sample(pids) if counter else None
                samples.append({"wall_s": time.perf_counter() - started,
                                "process_tree_cpu_percent_machine": cpu / (psutil.cpu_count() or 1),
                                "process_tree_cpu_percent_one_core": cpu,
                                "video_encode_percent": gpu})
            except psutil.Error:
                pass
            time.sleep(0.5)
    wall = time.perf_counter() - started
    if counter:
        counter.close()
    data = json.loads(result.read_text(encoding="utf-8")) if result.exists() else {}
    text = (out / "export.log").read_text(encoding="utf-8", errors="replace")
    summary = {"command": cmd, "qp_off": args.qp_off, "head": subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "dll_sha256": hashlib.sha256(native_dll.read_bytes()).hexdigest(),
        "layout_sha256": hashlib.sha256(layout.read_bytes()).hexdigest(), "exit_code": proc.returncode,
        "process_wall_seconds": wall, "harness": data, "resource_samples": samples,
        "gpu_counter_error": counter_error,
        "progress": re.findall(r"\[DIRECT PROGRESS\][^\n]+", text)}
    active_cpu = [s["process_tree_cpu_percent_machine"] for s in samples if s["process_tree_cpu_percent_machine"] > 0]
    active_gpu = [s["video_encode_percent"] for s in samples if s["video_encode_percent"] is not None and s["video_encode_percent"] > 0]
    summary["cpu_active_mean_percent_machine"] = sum(active_cpu) / len(active_cpu) if active_cpu else None
    summary["gpu_encode_active_mean_percent"] = sum(active_gpu) / len(active_gpu) if active_gpu else None
    (out / "measurement.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in summary.items() if k not in ("harness", "resource_samples", "progress", "command")}, indent=2))
    print("RESULT", data.get("success"), "effective_fps", data.get("effective_fps"),
          "stats", {k: v for k, v in data.get("stats", {}).items() if k.endswith("seconds") or "fps" in k})
    if proc.returncode or not data.get("success"):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
