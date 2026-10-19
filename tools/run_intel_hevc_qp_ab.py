"""A/B harness for the native Intel HEVC Slice QP readout.

Drives the canonical GUI harness (--test-intel-export) serially for HEVC Main10
HLG Fast/Balanced/Quality with TELEM_INTEL_QUANT_TELEMETRY on/off in ABBA order,
then verifies Slice QP against the independent Python bitstream analyzer.
"""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def run_one(out: Path, name: str, profile: str, frames: int, telemetry: bool, dll: str) -> dict:
    env = os.environ.copy()
    env.update(QT_QPA_PLATFORM="offscreen", TELEM_INTEL_NATIVE_DLL=dll,
               TELEM_INTEL_QUANT_TELEMETRY="1" if telemetry else "0")
    for key in ("TELEM_INTEL_TARGET_USAGE", "TELEM_INTEL_QSV_BITRATE_MBPS", "TELEM_INTEL_QP_TRACE", "TELEM_INTEL_FORCE_SERIAL_7D"):
        env.pop(key, None)
    mp4, result = out / f"{name}.mp4", out / f"{name}.json"
    result.unlink(missing_ok=True)
    cmd = [sys.executable, str(ROOT / "SportCamHUD.py"), "--test-intel-export", "--intel-path", "native", "--codec", "hevc",
           "--profile", profile, "--frames", str(frames), "--bitrate", "40M", "--video", r"C:\GoPro\GX010378.MP4",
           "--fit", r"C:\GoPro\2026-10-15_15-03-50.fit", "--layout", str(ROOT / "Raporty/intel_vbr_qp_20261017/layout.json"),
           "--watchdog-seconds", "900", "--output", str(mp4), "--result-json", str(result)]
    with (out / f"{name}.log").open("w", encoding="utf-8") as log:
        rc = subprocess.run(cmd, cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT).returncode
    item = json.loads(result.read_text(encoding="utf-8")) if result.exists() else {"success": False}
    item.update(name=name, profile=profile, telemetry=telemetry, returncode=rc, mp4=str(mp4))
    return item


def verify_per_frame(mp4: Path, dll: str) -> dict:
    """Native parser vs FFmpeg trace_headers on every frame of the exported stream."""
    os.environ["TELEM_INTEL_NATIVE_DLL"] = dll
    sys.path.insert(0, str(ROOT / "tests"))
    import test_intel_hevc_slice_qp_native as t
    annexb = mp4.with_suffix(".hevc")
    native, stats = t.native_parse(t.to_annexb(mp4, annexb))
    ref = t.reference_frames(annexb)
    annexb.unlink(missing_ok=True)
    mismatches = [i for i, (n, (r, _, _)) in enumerate(zip(native, ref)) if n < 0 or abs(n - r) > 1e-9]
    kinds = {k: sum(kind == k for _, kind, _ in ref) for k in "IPB"}
    return {"frames_native": len(native), "frames_reference": len(ref), "mismatched_frames": mismatches[:20],
            "mismatch_count": len(mismatches), "reference_frame_types": kinds,
            "native_frame_types": {"I": stats.type_frames[2], "P": stats.type_frames[1], "B": stats.type_frames[0]},
            "native_valid": stats.frames, "native_rejected": stats.rejected_frames,
            "sample_frames": [{"frame": i, "native": native[i], "reference": ref[i][0], "type": ref[i][1]}
                              for i in (0, 1, 30, 60, 61, len(ref) - 1) if i < len(ref)]}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--frames", type=int, default=600)
    parser.add_argument("--output", default="Raporty/intel_hevc_qp_20261017/ab")
    parser.add_argument("--dll", default=str(ROOT / "runtime/intel/bin/telem_intel_native.dll"))
    parser.add_argument("--repeats", type=int, default=2, help="ABBA blocks per preset")
    args = parser.parse_args()
    out = (ROOT / args.output).resolve(); out.mkdir(parents=True, exist_ok=True)
    from src.qp_analyzer import analyze_qp
    results = []
    for profile in ("fast", "balanced", "quality"):
        for rep, telemetry in enumerate((True, False, False, True) * args.repeats):
            name = f"hevc_{profile}_{'on' if telemetry else 'off'}_{rep}"
            print("START", name, flush=True)
            item = run_one(out, name, profile, args.frames, telemetry, args.dll)
            if telemetry and item.get("success"):
                ref = analyze_qp(item["mp4"])
                item["independent_qp_analyzer"] = {k: getattr(ref, k, None) for k in
                    ("codec", "bit_depth", "frames", "samples", "avg", "minimum", "maximum", "histogram",
                     "accuracy", "exact_block_qp", "error", "warnings")}
                item["per_frame_verification"] = verify_per_frame(Path(item["mp4"]), args.dll)
            results.append(item)
            stats = item.get("stats", {})
            print("DONE", name, "ok=", item.get("success"), "fps=", item.get("effective_fps"),
                  "slice_qp_avg=", stats.get("slice_qp_avg"), "text=", stats.get("compression_text"), flush=True)
            (out / "summary.json").write_text(json.dumps(results, indent=2, default=str), encoding="utf-8")


if __name__ == "__main__":
    main()
