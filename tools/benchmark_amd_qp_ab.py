#!/usr/bin/env python3
"""Automated A/B Benchmark for AMD Hardware QP Feedback Restoration.

Compares:
  Variant A (Baseline): runtime/amd/bin/telem_amd_native.dll (Production, QP OFF)
  Variant B (Candidate): scratch/amd_qp_candidate_20261020/telem_amd_native.dll (Candidate, QP ON)

Executes 3 alternating runs per variant (A1, B1, A2, B2, A3, B3) with 1200-1800 frames,
comparing median Render FPS, median Effective FPS, live mux finalization, and bitstream hashes.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import statistics
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path


def sha256_file(path: Path) -> str:
    if not path.is_file():
        return ""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(1024 * 1024):
            h.update(chunk)
    return h.hexdigest()


def run_benchmark_pass(
    repo_dir: Path,
    python_exe: Path,
    label: str,
    dll_path: Path,
    video_path: Path,
    fit_path: Path | None,
    layout_path: Path,
    frames: int,
    bitrate: str,
    quality: str,
    codec: str,
    out_dir: Path,
    mode: str = "direct",
    hdr_mode: str = "",
) -> dict:
    mp4_out = out_dir / f"{label}.mp4"
    json_out = out_dir / f"{label}.json"
    log_out = out_dir / f"{label}.log"

    if mp4_out.exists():
        mp4_out.unlink()
    if json_out.exists():
        json_out.unlink()

    cmd = [
        str(python_exe),
        str(repo_dir / "SportCamHUD.py"),
        "--test-amd-export",
        "--mode", mode,
        "--video", str(video_path),
        "--frames", str(frames),
        "--start-seconds", "0",
        "--quality", quality,
        "--codec", codec,
        "--bitrate", bitrate,
        "--layout", str(layout_path),
        "--output", str(mp4_out),
        "--result-json", str(json_out),
    ]
    if fit_path and fit_path.exists():
        cmd.extend(["--fit", str(fit_path)])
    if hdr_mode:
        cmd.extend(["--hdr-mode", hdr_mode])

    env = dict(os.environ)
    env["TELEM_AMD_NATIVE_DLL"] = str(dll_path.resolve())
    env["QT_QPA_PLATFORM"] = "offscreen"

    t0 = time.perf_counter()
    with open(log_out, "w", encoding="utf-8", errors="replace") as lf:
        proc = subprocess.run(cmd, cwd=repo_dir, env=env, stdout=lf, stderr=subprocess.STDOUT, timeout=1800)
    wall_duration = time.perf_counter() - t0

    result = {
        "label": label,
        "dll_path": str(dll_path),
        "dll_sha256": sha256_file(dll_path),
        "return_code": proc.returncode,
        "wall_duration_s": wall_duration,
        "mp4_sha256": sha256_file(mp4_out),
        "mp4_size_bytes": mp4_out.stat().st_size if mp4_out.exists() else 0,
    }

    if json_out.exists():
        try:
            with open(json_out, "r", encoding="utf-8") as jf:
                data = json.load(jf)
                result["json_data"] = data
                result["render_fps"] = data.get("render_fps") or data.get("real_export_fps") or 0.0
                result["effective_fps"] = data.get("effective_fps") or data.get("user_effective_fps") or 0.0
                result["avg_qp"] = data.get("avg_qp") or data.get("qp_avg")
                result["qp_samples"] = data.get("qp_samples", 0)
                result["mux_wait_ms"] = data.get("finalization_seconds", 0.0) * 1000.0
        except Exception as e:
            result["json_error"] = str(e)

    # Parse log for QP and timings if JSON lacks detail
    if log_out.exists():
        try:
            log_text = log_out.read_text(encoding="utf-8", errors="replace")
            for line in log_text.splitlines():
                if "Hardware QP stats:" in line:
                    result["log_qp_stats"] = line.strip()
                if "QP feedback diag:" in line:
                    result["log_qp_diag"] = line.strip()
                if "Render FPS =" in line and "render_fps" not in result:
                    # e.g. Render FPS = 39.970
                    parts = line.split("Render FPS =")
                    if len(parts) > 1:
                        try:
                            result["render_fps"] = float(parts[1].split()[0])
                        except Exception:
                            pass
                if "Effective FPS =" in line and "effective_fps" not in result:
                    parts = line.split("Effective FPS =")
                    if len(parts) > 1:
                        try:
                            result["effective_fps"] = float(parts[1].split()[0])
                        except Exception:
                            pass
        except Exception:
            pass

    return result


def main():
    parser = argparse.ArgumentParser(description="SportCamHUD AMD QP Restoration A/B Benchmark")
    parser.add_argument("--video", type=Path, default=Path(r"Video/GX020079.mp4"))
    parser.add_argument("--fit", type=Path, default=Path(r"Video/GX020079.fit"))
    parser.add_argument("--layout", type=Path, default=Path(r"def_layout.json"))
    parser.add_argument("--baseline-dll", type=Path, default=Path(r"runtime/amd/bin/telem_amd_native.dll"))
    parser.add_argument("--candidate-dll", type=Path, default=Path(r"scratch/amd_qp_candidate_20261020/telem_amd_native.dll"))
    parser.add_argument("--frames", type=int, default=1500)
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--bitrate", default="60M")
    parser.add_argument("--quality", default="FAST")
    parser.add_argument("--codec", default="hevc")
    parser.add_argument("--hdr-mode", default="")
    parser.add_argument("--output-dir", type=Path, default=Path(r"Raporty/amd_qp_ab_benchmarks"))
    args = parser.parse_args()

    repo_dir = Path(__file__).resolve().parents[1]
    python_exe = Path(sys.executable)

    out_dir = args.output_dir.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    video_path = (repo_dir / args.video).resolve() if not args.video.is_absolute() else args.video.resolve()
    fit_path = (repo_dir / args.fit).resolve() if args.fit and not args.fit.is_absolute() else (args.fit.resolve() if args.fit else None)
    layout_path = (repo_dir / args.layout).resolve() if not args.layout.is_absolute() else args.layout.resolve()
    baseline_dll = (repo_dir / args.baseline_dll).resolve() if not args.baseline_dll.is_absolute() else args.baseline_dll.resolve()
    candidate_dll = (repo_dir / args.candidate_dll).resolve() if not args.candidate_dll.is_absolute() else args.candidate_dll.resolve()

    if not video_path.is_file():
        print(f"Error: Video file not found: {video_path}")
        sys.exit(1)
    if not baseline_dll.is_file():
        print(f"Error: Baseline DLL not found: {baseline_dll}")
        sys.exit(1)
    if not candidate_dll.is_file():
        print(f"Error: Candidate DLL not found: {candidate_dll}")
        sys.exit(1)

    print("=" * 80)
    print("SportCamHUD AMD QP Restoration A/B Benchmark")
    print(f"Video: {video_path.name} ({args.frames} frames)")
    print(f"Codec: {args.codec} | Quality: {args.quality} | Bitrate: {args.bitrate}")
    print(f"Baseline DLL (QP OFF):  {baseline_dll} ({sha256_file(baseline_dll)[:12]}...)")
    print(f"Candidate DLL (QP ON):   {candidate_dll} ({sha256_file(candidate_dll)[:12]}...)")
    print(f"Alternating runs: {args.runs} pairs (Total {args.runs * 2} passes)")
    print("=" * 80)

    results_baseline = []
    results_candidate = []

    for run_idx in range(1, args.runs + 1):
        # 1. Baseline Run (Variant A)
        label_a = f"A{run_idx}_baseline_qpoff"
        print(f"\n[RUN {run_idx}/{args.runs}] Executing {label_a}...", flush=True)
        res_a = run_benchmark_pass(
            repo_dir, python_exe, label_a, baseline_dll, video_path, fit_path,
            layout_path, args.frames, args.bitrate, args.quality, args.codec, out_dir,
            hdr_mode=args.hdr_mode,
        )
        results_baseline.append(res_a)
        print(f"  -> Render FPS: {res_a.get('render_fps', 0):.2f} | Effective FPS: {res_a.get('effective_fps', 0):.2f} | ReturnCode: {res_a['return_code']}")

        # 2. Candidate Run (Variant B)
        label_b = f"B{run_idx}_candidate_qpon"
        print(f"[RUN {run_idx}/{args.runs}] Executing {label_b}...", flush=True)
        res_b = run_benchmark_pass(
            repo_dir, python_exe, label_b, candidate_dll, video_path, fit_path,
            layout_path, args.frames, args.bitrate, args.quality, args.codec, out_dir,
            hdr_mode=args.hdr_mode,
        )
        results_candidate.append(res_b)
        print(f"  -> Render FPS: {res_b.get('render_fps', 0):.2f} | Effective FPS: {res_b.get('effective_fps', 0):.2f} | QP avg: {res_b.get('avg_qp', 'N/A')} | ReturnCode: {res_b['return_code']}")

    # Statistical Evaluation
    fps_a_render = [r.get("render_fps", 0.0) for r in results_baseline if r.get("render_fps")]
    fps_b_render = [r.get("render_fps", 0.0) for r in results_candidate if r.get("render_fps")]
    fps_a_eff = [r.get("effective_fps", 0.0) for r in results_baseline if r.get("effective_fps")]
    fps_b_eff = [r.get("effective_fps", 0.0) for r in results_candidate if r.get("effective_fps")]

    med_a_render = statistics.median(fps_a_render) if fps_a_render else 0.0
    med_b_render = statistics.median(fps_b_render) if fps_b_render else 0.0
    med_a_eff = statistics.median(fps_a_eff) if fps_a_eff else 0.0
    med_b_eff = statistics.median(fps_b_eff) if fps_b_eff else 0.0

    delta_render_pct = ((med_b_render - med_a_render) / med_a_render * 100.0) if med_a_render > 0 else 0.0
    delta_eff_pct = ((med_b_eff - med_a_eff) / med_a_eff * 100.0) if med_a_eff > 0 else 0.0

    overhead_render_pct = -delta_render_pct if delta_render_pct < 0 else 0.0

    pass_decision = overhead_render_pct <= 1.0
    warn_decision = 1.0 < overhead_render_pct <= 2.0
    fail_decision = overhead_render_pct > 2.0

    status_str = "PASS" if pass_decision else ("WARN (overhead 1-2%)" if warn_decision else "FAIL (overhead > 2%)")

    # Bitstream check across runs
    hashes_b = {r["mp4_sha256"] for r in results_candidate if r.get("mp4_sha256")}
    bitstream_consistent = len(hashes_b) == 1

    summary = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "video": str(video_path),
        "frames": args.frames,
        "runs": args.runs,
        "status": status_str,
        "median_baseline_render_fps": med_a_render,
        "median_candidate_render_fps": med_b_render,
        "delta_render_pct": round(delta_render_pct, 2),
        "overhead_render_pct": round(overhead_render_pct, 2),
        "median_baseline_effective_fps": med_a_eff,
        "median_candidate_effective_fps": med_b_eff,
        "delta_effective_pct": round(delta_eff_pct, 2),
        "bitstream_consistent": bitstream_consistent,
        "candidate_qp_samples": [r.get("qp_samples") for r in results_candidate],
        "candidate_avg_qp": [r.get("avg_qp") for r in results_candidate],
        "results_baseline": results_baseline,
        "results_candidate": results_candidate,
    }

    summary_json_path = out_dir / "ab_benchmark_summary.json"
    with open(summary_json_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)

    # Print Summary Table
    print("\n" + "=" * 80)
    print("A/B BENCHMARK SUMMARY")
    print("=" * 80)
    print(f"Median Baseline Render FPS:  {med_a_render:.3f}")
    print(f"Median Candidate Render FPS: {med_b_render:.3f}")
    print(f"Render FPS Delta:            {delta_render_pct:+.2f}% (Overhead: {overhead_render_pct:.2f}%)")
    print(f"Median Baseline Eff FPS:     {med_a_eff:.3f}")
    print(f"Median Candidate Eff FPS:    {med_b_eff:.3f}")
    print(f"Effective FPS Delta:         {delta_eff_pct:+.2f}%")
    print(f"Candidate QP Avg:            {[r.get('avg_qp') for r in results_candidate]}")
    print(f"Bitstream Consistent:        {bitstream_consistent}")
    print(f"VERDICT:                     {status_str}")
    print("=" * 80)
    print(f"Summary saved to: {summary_json_path}")


if __name__ == "__main__":
    main()
