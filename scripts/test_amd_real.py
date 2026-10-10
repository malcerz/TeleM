"""Serial 800-frame AMD Direct/Queue benchmark on one verified VIDEO/FIT pair."""
from __future__ import annotations

import argparse
import json
import statistics
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def ffprobe(path: Path) -> dict:
    probe = ROOT / "ffprobe.exe"
    if not probe.exists():
        probe = Path("ffprobe")
    data = subprocess.check_output([
        str(probe), "-v", "error", "-count_frames", "-show_streams", "-show_format", "-of", "json", str(path),
    ], text=True)
    return json.loads(data)


def verify_sync_pair(video: Path, fit: Path) -> dict:
    result_path = ROOT / "scratch" / "amd_benchmark_sync.json"
    log_path = ROOT / "scratch" / "amd_benchmark_sync.log"
    process = subprocess.run([
        sys.executable, "BikeRideHUD.py", "--test-sync-integrity",
        "--video", str(video), "--fit", str(fit), "--result-json", str(result_path),
    ], cwd=ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    log_path.write_text(process.stdout, encoding="utf-8", errors="replace")
    if process.returncode != 0 or not result_path.is_file():
        raise RuntimeError(f"FIT/GPS SmartSync preflight failed; see {log_path}\n{process.stdout[-3000:]}")
    result = json.loads(result_path.read_text(encoding="utf-8"))
    smart_sync = result.get("smart_sync") or {}
    if result.get("status") != "VALID" or result.get("user_override") is not False:
        raise RuntimeError(f"Benchmark pair was not accepted without override: {result.get('status')}")
    if smart_sync.get("status") != "VALID" or smart_sync.get("gps_overlap") is not True:
        raise RuntimeError("Benchmark pair has no successful spatial SmartSync evidence")
    return result


def source_profile(video: Path) -> dict:
    probe = ROOT / "ffprobe.exe"
    if not probe.exists():
        probe = Path("ffprobe")
    data = subprocess.check_output([
        str(probe), "-v", "error", "-show_streams", "-show_format", "-of", "json", str(video),
    ], text=True)
    streams = json.loads(data).get("streams", [])
    stream = next((item for item in streams if item.get("codec_type") == "video"), None)
    if not stream:
        raise RuntimeError("Input video has no video stream")
    if stream.get("codec_name") != "hevc" or (int(stream.get("width", 0)), int(stream.get("height", 0))) != (3840, 2160):
        raise RuntimeError("Acceptance source must be 4K HEVC")
    num, den = (int(value) for value in stream.get("r_frame_rate", "0/1").split("/"))
    return {"source_fps": num / den if den else 0.0, "source_codec": stream.get("codec_name"), "width": stream.get("width"), "height": stream.get("height")}


def run_one(mode: str, preview: bool, repetition: int, video: Path, fit: Path, frames: int) -> dict:
    label = f"{mode}_preview_{'on' if preview else 'off'}_{repetition}"
    output = ROOT / "scratch" / f"{label}.mp4"
    result_json = ROOT / "scratch" / f"{label}.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    command = [
        sys.executable, "BikeRideHUD.py", "--test-amd-export", "--mode", mode,
        "--video", str(video), "--fit", str(fit), "--frames", str(frames),
        "--quality", "QUALITY", "--codec", "hevc", "--bitrate", "40M",
        "--output", str(output), "--result-json", str(result_json),
    ]
    if preview:
        command.append("--preview-hud")
    started = time.perf_counter()
    process = subprocess.run(command, cwd=ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    elapsed = time.perf_counter() - started
    log_path = ROOT / "scratch" / f"{label}.log"
    log_path.write_text(process.stdout, encoding="utf-8", errors="replace")
    if process.returncode:
        raise RuntimeError(f"{label} failed (rc={process.returncode}); see {log_path}\n{process.stdout[-3000:]}")
    if not output.is_file() or not result_json.is_file():
        raise RuntimeError(f"{label} did not produce MP4 and result JSON")
    result = json.loads(result_json.read_text(encoding="utf-8"))
    streams = ffprobe(output).get("streams", [])
    video_stream = next((stream for stream in streams if stream.get("codec_type") == "video"), None)
    audio_stream = next((stream for stream in streams if stream.get("codec_type") == "audio"), None)
    if not video_stream or video_stream.get("codec_name") != "hevc":
        raise RuntimeError(f"{label} output is not HEVC")
    if int(video_stream.get("width", 0)) != 3840 or int(video_stream.get("height", 0)) != 2160:
        raise RuntimeError(f"{label} output is not 3840x2160")
    actual_frames = int(video_stream.get("nb_read_frames", 0))
    if actual_frames < frames:
        raise RuntimeError(f"{label} output has only {actual_frames}/{frames} frames")
    if not audio_stream:
        raise RuntimeError(f"{label} output has no audio stream")
    video_duration = float(video_stream.get("duration", 0) or 0)
    audio_duration = float(audio_stream.get("duration", 0) or 0)
    if not video_duration or not audio_duration or abs(video_duration - audio_duration) > 0.5:
        raise RuntimeError(f"{label} audio/video duration mismatch ({audio_duration:.3f}s vs {video_duration:.3f}s)")
    if result.get("total_frames", 0) < frames:
        raise RuntimeError(f"{label} app reports too few frames")
    qp_samples = result.get("live_qp_samples") or []
    if not qp_samples:
        raise RuntimeError(f"{label} produced no live QP telemetry")
    return {
        "label": label, "mode": mode, "preview": preview, "frames": actual_frames,
        "elapsed_s": elapsed, "effective_fps": actual_frames / elapsed,
        "steady_render_fps": (result.get("stats") or {}).get("true_fps"),
        "startup_ms": result.get("startup_ms"), "output": str(output),
        "log": str(log_path), "profile": str(output) + ".amd_profile.json",
        "result_json": str(result_json), "audio": True, "qp_samples": len(qp_samples),
        "hevc": True,
        "resolution": "3840x2160", "quality": "QUALITY", "bitrate": "40M",
        "user_override": "USER_OVERRIDE=YES" in process.stdout,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--video", type=Path, required=True)
    parser.add_argument("--fit", type=Path, required=True)
    parser.add_argument("--frames", type=int, default=800)
    parser.add_argument("--pairs", type=int, default=3)
    parser.add_argument("--preview", choices=("on", "off", "both"), default="both")
    args = parser.parse_args()
    video, fit = args.video.resolve(), args.fit.resolve()
    if not video.is_file() or not fit.is_file():
        parser.error("VIDEO and FIT must both exist")
    if video.name.casefold() == "gx010321.mp4" and fit.name.casefold() == "poranna_jazda_na_rowerze.fit":
        parser.error("This VIDEO/FIT pairing is explicitly rejected and cannot be a benchmark fixture")
    if args.pairs < 3 or args.frames < 800:
        parser.error("Acceptance requires at least 3 pairs and 800 frames per export")

    results = []
    preflight = verify_sync_pair(video, fit)
    source = source_profile(video)
    preview_states = (True, False) if args.preview == "both" else (args.preview == "on",)
    # Serial execution prevents GPU benchmark overlap. Alternate ordering across
    # repetitions so Direct/Queue do not always inherit the same thermal order.
    for preview in preview_states:
        for repetition in range(1, args.pairs + 1):
            modes = ("direct", "queue") if repetition % 2 else ("queue", "direct")
            for mode in modes:
                row = run_one(mode, preview, repetition, video, fit, args.frames)
                results.append(row)
                print(json.dumps(row, ensure_ascii=False), flush=True)
    summary = {
        "video": str(video), "fit": str(fit), "source": source,
        "sync_preflight": preflight, "runs": results,
    }
    summary_path = ROOT / "scratch" / "amd_direct_queue_acceptance.json"
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    for preview in preview_states:
        for mode in ("direct", "queue"):
            fps = [row["effective_fps"] for row in results if row["preview"] == preview and row["mode"] == mode]
            print(f"{mode.upper()}_PREVIEW_{'ON' if preview else 'OFF'}_EFFECTIVE_FPS_MEDIAN={statistics.median(fps):.2f}")
    print(f"RESULT_JSON={summary_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
